from __future__ import annotations

import logging

from gal_radar.database import EventRecord, EventStore
from gal_radar.models.event import NotificationStatus
from gal_radar.notifications.telegram import TelegramNotifier, render_zh_tw_digest

logger = logging.getLogger(__name__)

MAX_EVENTS_PER_BATCH = 10


class DigestService:
    def __init__(self, store: EventStore, notifier: TelegramNotifier) -> None:
        self._store = store
        self._notifier = notifier

    async def send_digest(self) -> None:
        events = self._store.list_events_by_status(NotificationStatus.DIGEST)
        if not events:
            logger.info("No DIGEST events to send.")
            return

        def _sort_key(e: EventRecord) -> tuple[int, float, int]:
            ts = e.published_at.timestamp() if e.published_at else e.discovered_at.timestamp()
            return (-e.relevance_score, -ts, e.id)

        events.sort(key=_sort_key)

        for i in range(0, len(events), MAX_EVENTS_PER_BATCH):
            batch = events[i : i + MAX_EVENTS_PER_BATCH]
            digest_text = render_zh_tw_digest(batch)
            
            try:
                delivered = await self._notifier.send(digest_text)
                if delivered:
                    event_ids = [event.id for event in batch]
                    self._store.update_notification_statuses(event_ids, NotificationStatus.SENT)
                    logger.info(
                        "Digest batch sent successfully. Marked %d events as SENT.", len(batch)
                    )
                else:
                    logger.info("Digest batch not sent (likely dry-run). Database unchanged.")
            except Exception:
                logger.exception(
                    "Failed to send digest batch. Events remain in DIGEST status for retry."
                )
