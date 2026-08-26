from __future__ import annotations

import logging
from datetime import UTC, date

from gal_radar.adapters.base import SourceAdapter
from gal_radar.config import AppConfig
from gal_radar.database import EventRecord, EventStore
from gal_radar.models.event import EventType, NotificationStatus, SourceEvent
from gal_radar.notifications.base import NotificationSink
from gal_radar.notifications.telegram import render_zh_tw_notification
from gal_radar.services.change_detection import detect_change, snapshot_from_event
from gal_radar.services.deduplicate import find_duplicate
from gal_radar.services.normalize import normalize_event
from gal_radar.services.ranking import ScoreResult, score_event

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
        grouped: dict[str, list[SourceEvent]] = {}
        for event in source_events:
            raw_feed_key = event.metadata.get("feed_key")
            feed_key = str(raw_feed_key).strip() if raw_feed_key else source
            grouped.setdefault(feed_key, []).append(event)

        backfill_eligible = 0
        backfill_seen_eligible = 0
        backfill_duplicates = 0
        backfill_status_counts = {
            NotificationStatus.SENT.value: 0,
            NotificationStatus.DIGEST.value: 0,
            NotificationStatus.SKIPPED.value: 0,
            NotificationStatus.PENDING.value: 0,
            NotificationStatus.FAILED.value: 0,
        }

        for feed_key, events in grouped.items():
            if not self._store.is_baseline_initialized(feed_key):
                if self._dry_run:
                    logger.info(
                        "dry-run: feed baseline not persisted feed=%s items=%d",
                        feed_key,
                        len(events),
                    )
                    continue
                try:
                    for event in events:
                        self._store.mark_source_item_seen(source, event.source_event_id)
                    self._store.mark_baseline_initialized(feed_key)
                    logger.info("feed baseline initialized feed=%s", feed_key)
                except Exception:
                    logger.exception("feed baseline initialization failed feed=%s", feed_key)
                continue

            for event in events:
                seen = self._store.is_source_item_seen(source, event.source_event_id)
                backfill_candidate = self._is_backfill_candidate(event)
                if backfill_candidate:
                    backfill_eligible += 1
                    backfill_seen_eligible += int(seen)
                if seen and not backfill_candidate:
                    continue
                try:
                    if self._dry_run:
                        record = await self._preview_one(event)
                    else:
                        record = await self._process_one(event)

                    if record is None:
                        normalized = normalize_event(event)
                        duplicate = find_duplicate(self._store, normalized)
                        if backfill_candidate and duplicate is not None:
                            backfill_duplicates += 1
                        if (
                            not self._dry_run
                            and duplicate is not None
                            and duplicate.notification_status in _TERMINAL_STATUSES
                        ):
                            self._store.mark_source_item_seen(source, event.source_event_id)
                        continue
                    if backfill_candidate:
                        backfill_status_counts[record.notification_status] = (
                            backfill_status_counts.get(record.notification_status, 0) + 1
                        )
                    if not self._dry_run and record.notification_status in _TERMINAL_STATUSES:
                        self._store.mark_source_item_seen(source, event.source_event_id)
                    processed.append(record)
                except Exception:
                    logger.exception(
                        "feed event processing failed source=%s source_event_id=%s",
                        event.source,
                        event.source_event_id,
                    )

        if self._backfill_since is not None:
            published_dates = [
                published_date
                for event in source_events
                if (published_date := self._published_date(event)) is not None
            ]
            oldest = min(published_dates).isoformat() if published_dates else "none"
            newest = max(published_dates).isoformat() if published_dates else "none"
            logger.info(
                "backfill summary source=%s since=%s fetched=%d eligible=%d "
                "seen_eligible=%d duplicates=%d sent=%d digest=%d skipped=%d "
                "pending=%d failed=%d oldest=%s newest=%s",
                source,
                self._backfill_since.isoformat(),
                len(source_events),
                backfill_eligible,
                backfill_seen_eligible,
                backfill_duplicates,
                backfill_status_counts[NotificationStatus.SENT.value],
                backfill_status_counts[NotificationStatus.DIGEST.value],
                backfill_status_counts[NotificationStatus.SKIPPED.value],
                backfill_status_counts[NotificationStatus.PENDING.value],
                backfill_status_counts[NotificationStatus.FAILED.value],
                oldest,
                newest,
            )
        return processed

    def _published_date(self, event: SourceEvent) -> date | None:
        published_at = event.published_at
        if published_at is None:
            return None
        if published_at.tzinfo is not None and published_at.utcoffset() is not None:
            published_at = published_at.astimezone(UTC)
        return published_at.date()

    def _is_backfill_candidate(self, event: SourceEvent) -> bool:
        if self._backfill_since is None:
            return False
        published_date = self._published_date(event)
        return published_date is not None and published_date >= self._backfill_since

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
        status = self._preview_status(source_event, normalized.event_type, score)
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

    def _preview_status(
        self,
        source_event: SourceEvent,
        event_type: EventType,
        score: ScoreResult,
    ) -> NotificationStatus:
        if self._is_stale_snapshot_release(source_event):
            return NotificationStatus.SKIPPED
        if not self._event_type_enabled(event_type):
            return NotificationStatus.SKIPPED
        if score.score >= self._config.notification.immediate_threshold:
            return NotificationStatus.PENDING
        if score.score >= self._config.notification.digest_threshold:
            return NotificationStatus.DIGEST
        return NotificationStatus.SKIPPED

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
        if self._is_stale_snapshot_release(source_event):
            self._store.update_notification_status(record.id, NotificationStatus.SKIPPED)
            record.notification_status = NotificationStatus.SKIPPED.value
            logger.info(
                "notification skipped event_id=%s reason=stale_snapshot_release release_date=%s",
                record.id,
                source_event.metadata.get("release_date"),
            )
        elif not self._event_type_enabled(normalized.event_type):
            self._store.update_notification_status(record.id, NotificationStatus.SKIPPED)
            record.notification_status = NotificationStatus.SKIPPED.value
            logger.info(
                "notification skipped event_id=%s event_type=%s preference=disabled",
                record.id,
                normalized.event_type.value,
            )
        elif score.score >= self._config.notification.immediate_threshold:
            await self._deliver(record)
        elif score.score >= self._config.notification.digest_threshold:
            self._store.update_notification_status(record.id, NotificationStatus.DIGEST)
            record.notification_status = NotificationStatus.DIGEST.value
        else:
            self._store.update_notification_status(record.id, NotificationStatus.SKIPPED)
            record.notification_status = NotificationStatus.SKIPPED.value
        return record

    def _event_type_enabled(self, event_type: EventType) -> bool:
        return event_type in self._config.notification.enabled_event_types

    def _is_stale_snapshot_release(self, source_event: SourceEvent) -> bool:
        if source_event.source != "vndb" or source_event.event_type is not EventType.RELEASED:
            return False
        raw_release_date = source_event.metadata.get("release_date")
        if not isinstance(raw_release_date, str):
            return False
        try:
            release_date = date.fromisoformat(raw_release_date)
        except ValueError:
            return False
        age_days = (date.today() - release_date).days
        return age_days > self._config.notification.max_snapshot_release_age_days

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
