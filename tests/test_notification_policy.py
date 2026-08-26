from __future__ import annotations

from datetime import date, timedelta

from gal_radar.config import AppConfig
from gal_radar.models.event import EventType, NotificationStatus, SourceEvent
from gal_radar.services.notification_policy import choose_notification_status
from gal_radar.services.ranking import ScoreResult


def _event(*, event_type: EventType = EventType.DEVLOG, source: str = "steam") -> SourceEvent:
    return SourceEvent(
        source=source,
        source_event_id="123:1",
        vn_id="v1",
        event_type=event_type,
        title="Example VN",
        url="https://example.com/event",
    )


def test_notification_policy_maps_score_to_immediate_digest_and_skip() -> None:
    config = AppConfig()
    event = _event()

    assert (
        choose_notification_status(event, event.event_type, ScoreResult(70, ()), config)
        is NotificationStatus.PENDING
    )
    assert (
        choose_notification_status(event, event.event_type, ScoreResult(40, ()), config)
        is NotificationStatus.DIGEST
    )
    assert (
        choose_notification_status(event, event.event_type, ScoreResult(39, ()), config)
        is NotificationStatus.SKIPPED
    )


def test_notification_policy_skips_disabled_event_type() -> None:
    config = AppConfig.model_validate(
        {"notification": {"enabled_event_types": [EventType.RELEASED]}}
    )
    event = _event(event_type=EventType.DEVLOG)

    assert (
        choose_notification_status(event, event.event_type, ScoreResult(1000, ()), config)
        is NotificationStatus.SKIPPED
    )


def test_notification_policy_skips_stale_vndb_release() -> None:
    config = AppConfig.model_validate(
        {"notification": {"max_snapshot_release_age_days": 30}}
    )
    release_date = date.today() - timedelta(days=31)
    event = _event(event_type=EventType.RELEASED, source="vndb").model_copy(
        update={"metadata": {"release_date": release_date.isoformat()}}
    )

    assert (
        choose_notification_status(event, event.event_type, ScoreResult(1000, ()), config)
        is NotificationStatus.SKIPPED
    )
