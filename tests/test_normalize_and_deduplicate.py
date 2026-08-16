from __future__ import annotations

from datetime import UTC, datetime

from gal_radar.models.event import EventType, SourceEvent
from gal_radar.services.deduplicate import find_duplicate
from gal_radar.services.normalize import normalize_event
from gal_radar.services.ranking import ScoreResult


def source_event(*, source: str = "vndb", source_event_id: str = "event-1") -> SourceEvent:
    return SourceEvent(
        source=source,
        source_event_id=source_event_id,
        vn_id="v20431",
        developer_names=["枕"],
        tags=["nakige"],
        event_type=EventType.RELEASE_DATE,
        title="サクラノ刻",
        summary="Release date: 2026-10-30",
        url="https://vndb.org/v20431",
        metadata={"release_date": "2026-10-30"},
    )


def test_event_creation_has_stable_identity_and_hash() -> None:
    discovered_at = datetime(2026, 8, 16, tzinfo=UTC)
    event_a = normalize_event(source_event(), discovered_at=discovered_at)
    event_b = normalize_event(
        source_event(source="steam", source_event_id="steam-1"),
        discovered_at=discovered_at,
    )

    assert event_a.normalized_identity == event_b.normalized_identity
    assert event_a.content_hash == event_b.content_hash
    assert event_a.discovered_at == discovered_at


def test_cross_source_duplicate_is_detected(event_store) -> None:
    existing = normalize_event(source_event())
    event_store.add(existing, ScoreResult(score=90, reasons=("followed developer: 枕",)))

    duplicate = normalize_event(source_event(source="steam", source_event_id="steam-1"))

    found = find_duplicate(event_store, duplicate)
    assert found is not None
    assert found.source == "vndb"
