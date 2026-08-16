from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from gal_radar.models.event import EventType, SourceEvent

UNRELEASED = "unreleased"
RELEASED = "released"


@dataclass(frozen=True, slots=True)
class SourceSnapshotState:
    entity_key: str
    title: str
    developer_ids: tuple[str, ...]
    release_date: date | None
    release_state: str
    image_url: str | None
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))


def snapshot_from_event(
    event: SourceEvent,
    *,
    observed_at: datetime | None = None,
) -> SourceSnapshotState:
    release_date = parse_release_date(event.metadata.get("release_date"))
    release_state = _release_state(event)
    return SourceSnapshotState(
        entity_key=event.vn_id or event.source_event_id,
        title=event.title.strip(),
        developer_ids=tuple(developer_id for developer_id in event.developer_ids if developer_id),
        release_date=release_date,
        release_state=release_state,
        image_url=str(event.image_url) if event.image_url else None,
        observed_at=observed_at or datetime.now(UTC),
    )


def detect_change(
    previous: SourceSnapshotState | None,
    current: SourceEvent,
    baseline_initialized: bool,
) -> SourceEvent | None:
    if not baseline_initialized:
        return None

    current_state = snapshot_from_event(current)
    if previous is None or previous.entity_key != current_state.entity_key:
        return _transition_event(
            current,
            event_type=EventType.NEW_TITLE,
            source_event_id=f"{current_state.entity_key}:NEW_TITLE",
        )

    if previous.release_state != RELEASED and current_state.release_state == RELEASED:
        release_token = _date_token(current_state.release_date)
        return _transition_event(
            current,
            event_type=EventType.RELEASED,
            source_event_id=f"{current_state.entity_key}:RELEASED:{release_token}",
        )

    if previous.release_date is None and current_state.release_date is not None:
        release_date = current_state.release_date.isoformat()
        return _transition_event(
            current,
            event_type=EventType.RELEASE_DATE,
            source_event_id=f"{current_state.entity_key}:RELEASE_DATE:{release_date}",
        )

    if (
        previous.release_date is not None
        and current_state.release_date is not None
        and current_state.release_date != previous.release_date
    ):
        previous_date = previous.release_date.isoformat()
        new_date = current_state.release_date.isoformat()
        return _transition_event(
            current,
            event_type=EventType.DELAY,
            source_event_id=f"{current_state.entity_key}:DELAY:{previous_date}->{new_date}",
            metadata_updates={
                "previous_release_date": previous_date,
                "new_release_date": new_date,
                "release_date": new_date,
            },
        )

    return None


def parse_release_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped.upper() == "TBA":
        return None
    try:
        return date.fromisoformat(stripped)
    except ValueError:
        return None


def _release_state(event: SourceEvent) -> str:
    if event.event_type is EventType.RELEASED:
        return RELEASED
    if str(event.metadata.get("release_state", "")).casefold() == RELEASED:
        return RELEASED
    return UNRELEASED


def _transition_event(
    current: SourceEvent,
    *,
    event_type: EventType,
    source_event_id: str,
    metadata_updates: dict[str, str] | None = None,
) -> SourceEvent:
    metadata = dict(current.metadata)
    if metadata_updates:
        metadata.update(metadata_updates)
    return current.model_copy(
        update={
            "event_type": event_type,
            "source_event_id": source_event_id,
            "metadata": metadata,
        }
    )


def _date_token(value: date | None) -> str:
    return value.isoformat() if value is not None else "unknown"
