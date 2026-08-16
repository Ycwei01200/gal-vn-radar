from __future__ import annotations

import logging

from gal_radar.adapters.base import SourceAdapter
from gal_radar.config import AppConfig
from gal_radar.database import EventRecord, EventStore
from gal_radar.models.event import NotificationStatus, SourceEvent
from gal_radar.notifications.base import NotificationSink
from gal_radar.notifications.telegram import render_zh_tw_notification
from gal_radar.services.change_detection import detect_change, snapshot_from_event
from gal_radar.services.deduplicate import find_duplicate
from gal_radar.services.normalize import normalize_event
from gal_radar.services.ranking import score_event

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {
    NotificationStatus.DIGEST.value,
    NotificationStatus.SKIPPED.value,
    NotificationStatus.SENT.value,
}


class Pipeline:
    def __init__(
        self,
        *,
        config: AppConfig,
        store: EventStore,
        adapters: list[SourceAdapter],
        notifier: NotificationSink,
    ) -> None:
        self._config = config
        self._store = store
        self._adapters = adapters
        self._notifier = notifier
        self.successful_source_count = 0
        self.failed_source_count = 0

    async def run(self) -> list[EventRecord]:
        processed: list[EventRecord] = []
        self.successful_source_count = 0
        self.failed_source_count = 0
        for adapter in self._adapters:
            try:
                source_events = await adapter.fetch_events(self._config.follow)
                self.successful_source_count += 1
                logger.info("fetched %d events from %s", len(source_events), adapter.name)
                if getattr(adapter, "mode", "snapshot") == "feed":
                    processed.extend(await self._run_feed(adapter.name, source_events))
                else:
                    processed.extend(await self._run_snapshot(adapter.name, source_events))
            except Exception:
                self.failed_source_count += 1
                logger.exception("source fetch failed source=%s", adapter.name)
        return processed

    async def _run_snapshot(
        self,
        source: str,
        source_events: list[SourceEvent],
    ) -> list[EventRecord]:
        processed: list[EventRecord] = []
        if not self._store.is_baseline_initialized(source):
            try:
                for source_event in source_events:
                    self._store.save_snapshot(source, snapshot_from_event(source_event))
                self._store.mark_baseline_initialized(source)
            except Exception:
                logger.exception("source baseline initialization failed source=%s", source)
            return processed

        for source_event in source_events:
            try:
                previous = self._store.get_snapshot(
                    source,
                    source_event.vn_id or source_event.source_event_id,
                )
                changed_event = detect_change(
                    previous,
                    source_event,
                    baseline_initialized=True,
                )
                if changed_event is None:
                    self._store.save_snapshot(source, snapshot_from_event(source_event))
                    continue
                record = await self._process_one(changed_event)
                if record is None:
                    normalized = normalize_event(changed_event)
                    duplicate = find_duplicate(self._store, normalized)
                    if (
                        duplicate is not None
                        and duplicate.notification_status in _TERMINAL_STATUSES
                    ):
                        self._store.save_snapshot(source, snapshot_from_event(source_event))
                    continue
                if record.notification_status in _TERMINAL_STATUSES:
                    self._store.save_snapshot(source, snapshot_from_event(source_event))
            except Exception:
                logger.exception(
                    "event processing failed source=%s source_event_id=%s",
                    source_event.source,
                    source_event.source_event_id,
                )
                continue
            if record is not None:
                processed.append(record)
        return processed

    async def _run_feed(
        self,
        source: str,
        source_events: list[SourceEvent],
    ) -> list[EventRecord]:
        processed: list[EventRecord] = []
        grouped: dict[str, list[SourceEvent]] = {}
        for event in source_events:
            raw_feed_key = event.metadata.get("feed_key")
            feed_key = str(raw_feed_key).strip() if raw_feed_key else source
            grouped.setdefault(feed_key, []).append(event)

        for feed_key, events in grouped.items():
            if not self._store.is_baseline_initialized(feed_key):
                try:
                    for event in events:
                        self._store.mark_source_item_seen(source, event.source_event_id)
                    self._store.mark_baseline_initialized(feed_key)
                    logger.info("feed baseline initialized feed=%s", feed_key)
                except Exception:
                    logger.exception("feed baseline initialization failed feed=%s", feed_key)
                continue

            for event in events:
                if self._store.is_source_item_seen(source, event.source_event_id):
                    continue
                try:
                    record = await self._process_one(event)
                    if record is None:
                        normalized = normalize_event(event)
                        duplicate = find_duplicate(self._store, normalized)
                        if (
                            duplicate is not None
                            and duplicate.notification_status in _TERMINAL_STATUSES
                        ):
                            self._store.mark_source_item_seen(
                                source,
                                event.source_event_id,
                            )
                        continue
                    if record.notification_status in _TERMINAL_STATUSES:
                        self._store.mark_source_item_seen(source, event.source_event_id)
                    processed.append(record)
                except Exception:
                    logger.exception(
                        "feed event processing failed source=%s source_event_id=%s",
                        event.source,
                        event.source_event_id,
                    )
        return processed

    async def _process_one(self, source_event: SourceEvent) -> EventRecord | None:
        normalized = normalize_event(source_event)
        duplicate = find_duplicate(self._store, normalized)
        if duplicate is not None:
            is_different_source_item = (
                duplicate.source != source_event.source
                or duplicate.source_event_id != source_event.source_event_id
            )
            if is_different_source_item:
                corroboration = {
                    "source": source_event.source,
                    "source_event_id": source_event.source_event_id,
                    "url": str(source_event.url),
                    "published_at": (
                        source_event.published_at.isoformat()
                        if source_event.published_at
                        else None
                    ),
                }
                self._store.add_corroborating_source(duplicate.id, corroboration)
                logger.info(
                    "event duplicate event_id=%s source=%s corroborated=true",
                    duplicate.id,
                    source_event.source,
                )
            else:
                logger.info("skipped duplicate event_id=%s", duplicate.id)
            if duplicate.notification_status == NotificationStatus.SENT.value:
                return None
            retry_statuses = {
                NotificationStatus.PENDING.value,
                NotificationStatus.FAILED.value,
            }
            if (
                duplicate.relevance_score >= self._config.notification.immediate_threshold
                and duplicate.notification_status in retry_statuses
            ):
                await self._deliver(duplicate)
                return duplicate
            return None

        score = score_event(normalized, self._config)
        record = self._store.add(normalized, score)
        if score.score >= self._config.notification.immediate_threshold:
            await self._deliver(record)
        elif score.score >= self._config.notification.digest_threshold:
            self._store.update_notification_status(record.id, NotificationStatus.DIGEST)
            record.notification_status = NotificationStatus.DIGEST.value
        else:
            self._store.update_notification_status(record.id, NotificationStatus.SKIPPED)
            record.notification_status = NotificationStatus.SKIPPED.value
        return record

    async def _deliver(self, record: EventRecord) -> None:
        message = render_zh_tw_notification(record)
        try:
            try:
                delivered = await self._notifier.send(message, image_url=record.image_url)
            except TypeError as exc:
                if "image_url" not in str(exc):
                    raise
                delivered = await self._notifier.send(message)
        except Exception:
            self._store.update_notification_status(record.id, NotificationStatus.FAILED)
            record.notification_status = NotificationStatus.FAILED.value
            logger.exception("notification failed event_id=%s", record.id)
            return
        if delivered:
            self._store.update_notification_status(record.id, NotificationStatus.SENT)
            record.notification_status = NotificationStatus.SENT.value
            logger.info("notification sent event_id=%s", record.id)
