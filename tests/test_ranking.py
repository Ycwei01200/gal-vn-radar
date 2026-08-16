from gal_radar.models.event import EventType, SourceEvent
from gal_radar.services.normalize import normalize_event
from gal_radar.services.ranking import score_event


def test_relevance_scoring_is_deterministic_and_explainable(app_config) -> None:
    event = normalize_event(
        SourceEvent(
            source="vndb",
            source_event_id="v20431:RELEASE_DATE:2026-10-30",
            vn_id="v20431",
            developer_names=["枕"],
            tags=["nakige", "drama"],
            event_type=EventType.RELEASE_DATE,
            title="サクラノ刻",
            url="https://vndb.org/v20431",
            metadata={"release_date": "2026-10-30"},
        )
    )

    result = score_event(event, app_config)

    assert result.score == 200
    assert result.reasons == (
        "followed visual novel",
        "followed developer: 枕",
        "matched tag: nakige",
        "event type: RELEASE_DATE",
    )
