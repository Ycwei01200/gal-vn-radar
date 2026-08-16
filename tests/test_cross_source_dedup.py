from __future__ import annotations

from gal_radar.models.event import EventType, SourceEvent
from gal_radar.services.deduplicate import find_duplicate
from gal_radar.services.normalize import normalize_event
from gal_radar.services.ranking import ScoreResult


def _event(
    *,
    source: str,
    source_event_id: str,
    event_type: EventType,
    release_date: str | None = None,
    news_title: str | None = None,
) -> SourceEvent:
    metadata: dict[str, object] = {}
    if release_date is not None:
        metadata["release_date"] = release_date
    if news_title is not None:
        metadata["news_title"] = news_title
    return SourceEvent(
        source=source,
        source_event_id=source_event_id,
        vn_id="v20431",
        event_type=event_type,
        title="サクラノ刻－櫻の森の下を歩む－",
        summary="source-specific text",
        url=(
            "https://vndb.org/v20431"
            if source == "vndb"
            else "https://store.steampowered.com/news/app/123456/view/999"
        ),
        metadata=metadata,
    )


def test_released_event_deduplicates_across_vndb_and_steam(event_store) -> None:
    vndb = normalize_event(
        _event(
            source="vndb",
            source_event_id="v20431:RELEASED:2026-10-30",
            event_type=EventType.RELEASED,
            release_date="2026-10-30",
        )
    )
    event_store.add(vndb, ScoreResult(score=100, reasons=("followed visual novel",)))

    steam = normalize_event(
        _event(
            source="steam",
            source_event_id="123456:999",
            event_type=EventType.RELEASED,
            news_title="Now available on Steam",
        )
    )

    assert steam.normalized_identity == vndb.normalized_identity
    duplicate = find_duplicate(event_store, steam)
    assert duplicate is not None
    assert duplicate.source == "vndb"


def test_release_date_event_deduplicates_when_new_date_matches(event_store) -> None:
    vndb = normalize_event(
        _event(
            source="vndb",
            source_event_id="v20431:RELEASE_DATE:2026-10-30",
            event_type=EventType.RELEASE_DATE,
            release_date="2026-10-30",
        )
    )
    event_store.add(vndb, ScoreResult(score=100, reasons=("followed visual novel",)))

    steam = normalize_event(
        _event(
            source="steam",
            source_event_id="123456:1000",
            event_type=EventType.RELEASE_DATE,
            release_date="2026-10-30",
            news_title="Release Date Announced: October 30, 2026",
        )
    )

    assert steam.normalized_identity == vndb.normalized_identity
    assert find_duplicate(event_store, steam) is not None


def test_different_patch_headlines_do_not_collapse_into_one_event() -> None:
    patch_one = normalize_event(
        _event(
            source="steam",
            source_event_id="123456:1",
            event_type=EventType.PATCH,
            news_title="Patch 1.1",
        )
    )
    patch_two = normalize_event(
        _event(
            source="steam",
            source_event_id="123456:2",
            event_type=EventType.PATCH,
            news_title="Patch 1.2",
        )
    )

    assert patch_one.normalized_identity != patch_two.normalized_identity
