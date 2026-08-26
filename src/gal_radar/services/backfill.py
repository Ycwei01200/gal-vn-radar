from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date

from gal_radar.models.event import SourceEvent


def published_date(event: SourceEvent) -> date | None:
    published_at = event.published_at
    if published_at is None:
        return None
    if published_at.tzinfo is not None and published_at.utcoffset() is not None:
        published_at = published_at.astimezone(UTC)
    return published_at.date()


def is_backfill_candidate(event: SourceEvent, since: date | None) -> bool:
    if since is None:
        return False
    event_date = published_date(event)
    return event_date is not None and event_date >= since


@dataclass(slots=True)
class BackfillStats:
    source: str
    since: date
    fetched: int
    oldest: date | None = None
    newest: date | None = None
    eligible: int = 0
    seen_eligible: int = 0
    duplicates: int = 0
    status_counts: Counter[str] = field(default_factory=Counter)

    @classmethod
    def from_events(
        cls,
        source: str,
        since: date,
        events: list[SourceEvent],
    ) -> BackfillStats:
        dates = [
            event_date
            for event in events
            if (event_date := published_date(event)) is not None
        ]
        return cls(
            source=source,
            since=since,
            fetched=len(events),
            oldest=min(dates) if dates else None,
            newest=max(dates) if dates else None,
        )

    def record_candidate(self, *, seen: bool) -> None:
        self.eligible += 1
        self.seen_eligible += int(seen)

    def record_duplicate(self) -> None:
        self.duplicates += 1

    def record_status(self, status: str) -> None:
        self.status_counts[status] += 1

    def log(self, logger: logging.Logger) -> None:
        logger.info(
            "backfill summary source=%s since=%s fetched=%d eligible=%d "
            "seen_eligible=%d duplicates=%d sent=%d digest=%d skipped=%d "
            "pending=%d failed=%d oldest=%s newest=%s",
            self.source,
            self.since.isoformat(),
            self.fetched,
            self.eligible,
            self.seen_eligible,
            self.duplicates,
            self.status_counts["SENT"],
            self.status_counts["DIGEST"],
            self.status_counts["SKIPPED"],
            self.status_counts["PENDING"],
            self.status_counts["FAILED"],
            self.oldest.isoformat() if self.oldest else "none",
            self.newest.isoformat() if self.newest else "none",
        )
