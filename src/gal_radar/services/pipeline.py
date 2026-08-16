from __future__ import annotations

import logging

from gal_radar.adapters.base import SourceAdapter
from gal_radar.config import AppConfig
from gal_radar.database import EventRecord, EventStore
from gal_radar.models.event import NotificationStatus, SourceEvent
from gal_radar.notifications.base import NotificationSink
from gal_radar.notifications.telegram import render_zh_tw_notification
from gal_radar.services.deduplicate import find_duplicate
from gal_radar.services.normalize import normalize_event
from gal_radar.services.ranking import score_event

logger = logging.getLogger(__name__)


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

    async def run(self) -> list[EventRecord]:
        processed: list[EventRecord] = []
        for adapter in self._adapters:
            source_events = await adapter.fetch_events(self._config.follow)
            logger.info("fetched %d events from %s", len(source_events), adapter.name)
            for source_event in source_events:
                try:
                    record = await self._process_one(source_event)
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

    async def _process_one(self, source_event: SourceEvent) -> EventRecord | None:
        normalized = normalize_event(source_event)
        duplicate = find_duplicate(self._store, normalized)
        if duplicate is not None:
            if duplicate.notification_status == NotificationStatus.SENT.value:
                logger.info("skipped duplicate event_id=%s", duplicate.id)
                return None
            if (
                duplicate.relevance_score >= self._config.notification.immediate_threshold
                and duplicate.notification_status
                in {NotificationStatus.PENDING.value, NotificationStatus.FAILED.value}
            ):
                await self._deliver(duplicate)
                return duplicate
            logger.info("skipped duplicate event_id=%s", duplicate.id)
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
