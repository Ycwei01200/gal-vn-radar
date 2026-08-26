from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

from gal_radar.models.event import EventType, SourceEvent
from gal_radar.services.backfill import BackfillStats, is_backfill_candidate, published_date


def _event(published_at: datetime | None) -> SourceEvent:
    return SourceEvent(
        source="steam",
        source_event_id="123:1",
        vn_id="v1",
        event_type=EventType.DEVLOG,
        title="Example VN",
        url="https://store.steampowered.com/news/app/123/view/1",
        published_at=published_at,
        metadata={"feed_key": "steam:123"},
    )


def test_published_date_normalizes_aware_timestamp_to_utc() -> None:
    taipei = timezone(timedelta(hours=8))
    event = _event(datetime(2026, 8, 16, 7, 30, tzinfo=taipei))

    assert published_date(event) == date(2026, 8, 15)


def test_backfill_candidate_uses_inclusive_utc_date_cutoff() -> None:
    event = _event(datetime(2026, 8, 16, 0, 0, tzinfo=UTC))

    assert is_backfill_candidate(event, date(2026, 8, 16)) is True
    assert is_backfill_candidate(event, date(2026, 8, 17)) is False


def test_backfill_stats_tracks_range_candidates_duplicates_and_statuses() -> None:
    events = [
        _event(datetime(2026, 8, 15, tzinfo=UTC)),
        _event(datetime(2026, 8, 20, tzinfo=UTC)),
    ]
    stats = BackfillStats.from_events("steam", date(2026, 8, 16), events)

    stats.record_candidate(seen=True)
    stats.record_duplicate()
    stats.record_status("SENT")

    assert stats.fetched == 2
    assert stats.oldest == date(2026, 8, 15)
    assert stats.newest == date(2026, 8, 20)
    assert stats.eligible == 1
    assert stats.seen_eligible == 1
    assert stats.duplicates == 1
    assert stats.status_counts["SENT"] == 1
