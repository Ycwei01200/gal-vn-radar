from __future__ import annotations

from datetime import date

from gal_radar.config import AppConfig
from gal_radar.models.event import EventType, NotificationStatus, SourceEvent
from gal_radar.services.ranking import ScoreResult


def choose_notification_status(
    source_event: SourceEvent,
    event_type: EventType,
    score: ScoreResult,
    config: AppConfig,
) -> NotificationStatus:
    if is_stale_snapshot_release(source_event, config):
        return NotificationStatus.SKIPPED
    if event_type not in config.notification.enabled_event_types:
        return NotificationStatus.SKIPPED
    if score.score >= config.notification.immediate_threshold:
        return NotificationStatus.PENDING
    if score.score >= config.notification.digest_threshold:
        return NotificationStatus.DIGEST
    return NotificationStatus.SKIPPED


def is_stale_snapshot_release(source_event: SourceEvent, config: AppConfig) -> bool:
    if source_event.source != "vndb" or source_event.event_type is not EventType.RELEASED:
        return False
    raw_release_date = source_event.metadata.get("release_date")
    if not isinstance(raw_release_date, str):
        return False
    try:
        release_date = date.fromisoformat(raw_release_date)
    except ValueError:
        return False
    age_days = (date.today() - release_date).days
    return age_days > config.notification.max_snapshot_release_age_days
