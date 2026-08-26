from __future__ import annotations

import logging
from datetime import date

from gal_radar.adapters.base import SourceAdapter
from gal_radar.config import AppConfig
from gal_radar.database import EventRecord, EventStore
from gal_radar.models.event import EventType, NotificationStatus, SourceEvent
from gal_radar.notifications.base import NotificationSink
from gal_radar.notifications.telegram import render_zh_tw_notification
from gal_radar.services.backfill import BackfillStats, is_backfill_candidate
from gal_radar.services.change_detection import detect_change, snapshot_from_event
from gal_radar.services.deduplicate import find_duplicate
from gal_radar.services.normalize import normalize_event
from gal_radar.services.notification_policy import (
    choose_notification_status,
    is_stale_snapshot_release,
)
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
        dry_run: bool = False,
        backfill_since: date | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._adapters = adapters
        self._notifier = notifier
        self._dry_run = dry_run
        self._backfill_since = backfill_since
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
            if self._dry_run:
                logger.info(
                    "dry-run: snapshot baseline not persisted source=%s events=%d",
                    source,
                    len(source_events),
                )
                return processed
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
                    if not self._dry_run:
                        self._store.save_snapshot(source, snapshot_from_event(source_event))
                    continue

                if self._dry_run:
                    record = await self._preview_one(changed_event)
                    if record is not None:
                        processed.append(record)
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
        grouped = self._group_feed_events(source, source_events)
        stats = (
            BackfillStats.from_events(source, self._backfill_since, source_events)
            if self._backfill_since is not None
            else None
        )

        for feed_key, events in grouped.items():
            if not self._store.is_baseline_initialized(feed_key):
                self._initialize_feed_baseline(source, feed_key, events)
                continue

            for event in events:
                seen = self._store.is_source_item_seen(source, event.source_event_id)
                backfill_candidate = is_backfill_candidate(event, self._backfill_since)
                if backfill_candidate and stats is not None:
                    stats.record_candidate(seen=seen)
                if seen and not backfill_candidate:
                    continue

                record = await self._process_feed_event(
                    source,
                    event,
                    backfill_candidate=backfill_candidate,
                    stats=stats,
                )
                if record is not None:
                    processed.append(record)

        if stats is not None:
            stats.log(logger)
        return processed

    @staticmethod
    def _group_feed_events(
        source: str,
        source_events: list[SourceEvent],
    ) -> dict[str, list[SourceEvent]]:
        grouped: dict[str, list[SourceEvent]] = {}
        for event in source_events:
            raw_feed_key = event.metadata.get("feed_key")
            feed_key = str(raw_feed_key).strip() if raw_feed_key else source
            grouped.setdefault(feed_key, []).append(event)
        return grouped

    def _initialize_feed_baseline(
        self,
        source: str,
        feed_key: str,
        events: list[SourceEvent],
    ) -> None:
        if self._dry_run:
            logger.info(
                "dry-run: feed baseline not persisted feed=%s items=%d",
                feed_key,
                len(events),
            )
            return
        try:
            for event in events:
                self._store.mark_source_item_seen(source, event.source_event_id)
            self._store.mark_baseline_initialized(feed_key)
            logger.info("feed baseline initialized feed=%s", feed_key)
        except Exception:
            logger.exception("feed baseline initialization failed feed=%s", feed_key)

    async def _process_feed_event(
        self,
        source: str,
        event: SourceEvent,
        *,
        backfill_candidate: bool,
        stats: BackfillStats | None,
    ) -> EventRecord | None:
        try:
            if self._dry_run:
                record = await self._preview_one(event)
            else:
                record = await self._process_one(event)

            if record is None:
                normalized = normalize_event(event)
                duplicate = find_duplicate(self._store, normalized)
                if backfill_candidate and stats is not None and duplicate is not None:
                    stats.record_duplicate()
                if (
                    not self._dry_run
                    and duplicate is not None
                    and duplicate.notification_status in _TERMINAL_STATUSES
                ):
                    self._store.mark_source_item_seen(source, event.source_event_id)
                return None

            if backfill_candidate and stats is not None:
                stats.record_status(record.notification_status)
            if not self._dry_run and record.notification_status in _TERMINAL_STATUSES:
                self._store.mark_source_item_seen(source, event.source_event_id)
            return record
        except Exception:
            logger.exception(
                "feed event processing failed source=%s source_event_id=%s",
                event.source,
                event.source_event_id,
            )
            return None

    async def _preview_one(self, source_event: SourceEvent) -> EventRecord | None:
        normalized = normalize_event(source_event)
        duplicate = find_duplicate(self._store, normalized)
        if duplicate is not None:
            if not self._event_type_enabled(EventType(duplicate.event_type)):
                return None
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
                await self._preview_delivery(duplicate)
                return duplicate
            return None

        score = score_event(normalized, self._config)
        status = choose_notification_status(
            source_event,
            normalized.event_type,
            score,
            self._config,
        )
        record = EventRecord(
            source=normalized.source,
            source_event_id=normalized.source_event_id,
            vn_id=normalized.vn_id,
            developer_id=normalized.developer_id,
            developer_names=normalized.developer_names,
            tags=normalized.tags,
            event_type=normalized.event_type.value,
            title=normalized.title,
            summary=normalized.summary,
            url=normalized.url,
            image_url=normalized.image_url,
            published_at=normalized.published_at,
            discovered_at=normalized.discovered_at,
            normalized_identity=normalized.normalized_identity,
            content_hash=normalized.content_hash,
            metadata_json=normalized.metadata,
            relevance_score=score.score,
            relevance_reasons=list(score.reasons),
            notification_status=status.value,
            corroborating_sources=[],
        )
        if status is NotificationStatus.PENDING:
            await self._preview_delivery(record)
        return record

    async def _preview_delivery(self, record: EventRecord) -> None:
        message = render_zh_tw_notification(
            record,
            source_priority=self._config.preferences.source_priority,
        )
        try:
            try:
                await self._notifier.send(message, image_url=record.image_url)
            except TypeError as exc:
                if "image_url" not in str(exc):
                    raise
                await self._notifier.send(message)
        except Exception:
            logger.exception(
                "dry-run notification preview failed source=%s source_event_id=%s",
                record.source,
                record.source_event_id,
            )

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
            if not self._event_type_enabled(EventType(duplicate.event_type)):
                return None
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
        status = choose_notification_status(
            source_event,
            normalized.event_type,
            score,
            self._config,
        )

        if status is NotificationStatus.PENDING:
            await self._deliver(record)
        else:
            self._store.update_notification_status(record.id, status)
            record.notification_status = status.value
            if status is NotificationStatus.SKIPPED:
                if is_stale_snapshot_release(source_event, self._config):
                    logger.info(
                        "notification skipped event_id=%s reason=stale_snapshot_release "
                        "release_date=%s",
                        record.id,
                        source_event.metadata.get("release_date"),
                    )
                elif not self._event_type_enabled(normalized.event_type):
                    logger.info(
                        "notification skipped event_id=%s event_type=%s preference=disabled",
                        record.id,
                        normalized.event_type.value,
                    )
        return record

    def _event_type_enabled(self, event_type: EventType) -> bool:
        return event_type in self._config.notification.enabled_event_types

    async def _deliver(self, record: EventRecord) -> None:
        message = render_zh_tw_notification(
            record,
            source_priority=self._config.preferences.source_priority,
        )
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
