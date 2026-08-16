from __future__ import annotations

import logging

from gal_radar.database import EventStore
from gal_radar.models.event import NotificationStatus
from gal_radar.notifications.telegram import TelegramNotifier, render_zh_tw_digest

logger = logging.getLogger(__name__)


class DigestService:
    def __init__(self, store: EventStore, notifier: TelegramNotifier) -> None:
        self._store = store
        self._notifier = notifier

    async def send_digest(self) -> None:
        events = self._store.list_events_by_status(NotificationStatus.DIGEST)
        if not events:
            logger.info("No DIGEST events to send.")
            return

        digest_text = render_zh_tw_digest(events)
        
        try:
            delivered = await self._notifier.send(digest_text)
            if delivered:
                event_ids = [event.id for event in events]
                self._store.update_notification_statuses(event_ids, NotificationStatus.SENT)
                logger.info("Digest sent successfully. Marked %d events as SENT.", len(events))
            else:
                logger.info("Digest not sent (likely dry-run). Database unchanged.")
        except Exception:
            logger.exception("Failed to send digest. Events remain in DIGEST status for retry.")
