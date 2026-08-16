from gal_radar.config import AppConfig
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


def test_relevance_scoring_matches_resolved_developer_id_with_canonical_name() -> None:
    app_config = AppConfig.model_validate(
        {
            "follow": {
                "developers": ["枕"],
                "visual_novels": ["v20431"],
                "tags": ["nakige"],
            },
            "notification": {
                "immediate_threshold": 70,
                "digest_threshold": 40,
            },
        }
    )
    app_config.follow.set_resolved_developer_ids(["p30"])
    event = normalize_event(
        SourceEvent(
            source="vndb",
            source_event_id="v20431:RELEASE_DATE:2026-10-30",
            vn_id="v20431",
            developer_id="p30",
            developer_ids=["p30"],
            developer_names=["Makura"],
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
        "followed developer: Makura",
        "matched tag: nakige",
        "event type: RELEASE_DATE",
    )


def test_auto_discovered_vn_promotes_important_events_but_not_other() -> None:
    config = AppConfig()
    config.follow.add_discovered_vn("v50000")

    released = normalize_event(
        SourceEvent(
            source="steam",
            source_event_id="123:released",
            vn_id="v50000",
            event_type=EventType.RELEASED,
            title="Example VN",
            url="https://example.com/released",
        )
    )
    patch = released.model_copy(update={"event_type": EventType.PATCH})
    other = released.model_copy(update={"event_type": EventType.OTHER})

    assert score_event(released, config).score == 70
    assert score_event(patch, config).score == 50
    assert score_event(other, config).score == 0
