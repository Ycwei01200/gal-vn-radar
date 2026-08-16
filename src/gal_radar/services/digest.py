from __future__ import annotations

import logging

from gal_radar.database import EventRecord, EventStore
from gal_radar.models.event import NotificationStatus
from gal_radar.notifications.telegram import TelegramNotifier, render_zh_tw_digest

logger = logging.getLogger(__name__)

MAX_EVENTS_PER_BATCH = 10


class DigestService:
    def __init__(
        self,
        store: EventStore,
        notifier: TelegramNotifier,
        *,
        source_priority: list[str] | None = None,
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._source_priority = source_priority

    async def send_digest(self) -> None:
        events = self._store.list_events_by_status(NotificationStatus.DIGEST)
        if not events:
            logger.info("No DIGEST events to send.")
            return

        def _sort_key(event: EventRecord) -> tuple[int, float, int]:
            timestamp = (
                event.published_at.timestamp()
                if event.published_at
                else event.discovered_at.timestamp()
            )
            return (-event.relevance_score, -timestamp, event.id)

        events.sort(key=_sort_key)

        for index in range(0, len(events), MAX_EVENTS_PER_BATCH):
            batch = events[index : index + MAX_EVENTS_PER_BATCH]
            digest_text = render_zh_tw_digest(
                batch,
                source_priority=self._source_priority,
            )
            try:
                delivered = await self._notifier.send(digest_text)
                if delivered:
                    event_ids = [event.id for event in batch]
                    self._store.update_notification_statuses(
                        event_ids,
                        NotificationStatus.SENT,
                    )
                    logger.info(
                        "Digest batch sent successfully. Marked %d events as SENT.",
                        len(batch),
                    )
                else:
                    logger.info("Digest batch not sent (likely dry-run). Database unchanged.")
            except Exception:
                logger.exception(
                    "Failed to send digest batch. Events remain in DIGEST status for retry."
                )
