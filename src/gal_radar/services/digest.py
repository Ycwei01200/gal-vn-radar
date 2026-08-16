from __future__ import annotations

import logging
from datetime import date

from gal_radar.database import EventRecord, EventStore
from gal_radar.models.event import EventType, NotificationStatus
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
        max_snapshot_release_age_days: int = 30,
        prune_stale: bool = True,
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._source_priority = source_priority
        self._max_snapshot_release_age_days = max_snapshot_release_age_days
        self._prune_stale = prune_stale

    async def send_digest(self) -> None:
        events = self._store.list_events_by_status(NotificationStatus.DIGEST)
        stale_events = [event for event in events if self._is_stale_snapshot_release(event)]
        if stale_events:
            stale_ids = [event.id for event in stale_events]
            if self._prune_stale:
                self._store.update_notification_statuses(
                    stale_ids,
                    NotificationStatus.SKIPPED,
                )
                logger.info(
                    "Skipped %d stale VNDB release events before digest delivery.",
                    len(stale_events),
                )
            else:
                logger.info(
                    "Suppressed %d stale VNDB release events from dry-run digest; "
                    "database unchanged.",
                    len(stale_events),
                )
            stale_id_set = set(stale_ids)
            events = [event for event in events if event.id not in stale_id_set]

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

    def _is_stale_snapshot_release(self, event: EventRecord) -> bool:
        if event.source != "vndb" or event.event_type != EventType.RELEASED.value:
            return False
        raw_release_date = event.metadata_json.get("release_date")
        if not isinstance(raw_release_date, str):
            return False
        try:
            release_date = date.fromisoformat(raw_release_date)
        except ValueError:
            return False
        age_days = (date.today() - release_date).days
        return age_days > self._max_snapshot_release_age_days
