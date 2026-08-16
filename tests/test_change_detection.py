from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from gal_radar.database import EventStore
from gal_radar.models.event import EventType, SourceEvent
from gal_radar.services.change_detection import (
    SourceSnapshotState,
    detect_change,
    snapshot_from_event,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "change_detection"
OBSERVED_AT = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def load_fixture(name: str) -> SourceEvent:
    payload = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return SourceEvent.model_validate(payload)


def test_first_observation_initializes_baseline_without_historical_event() -> None:
    current = load_fixture("future")

    assert detect_change(None, current, baseline_initialized=False) is None


def test_uninitialized_baseline_suppresses_existing_snapshot_changes() -> None:
    previous = snapshot_from_event(load_fixture("future"), observed_at=OBSERVED_AT)
    current = load_fixture("delayed")

    assert detect_change(previous, current, baseline_initialized=False) is None


def test_unseen_title_after_baseline_emits_new_title() -> None:
    current = load_fixture("new_title")

    change = detect_change(None, current, baseline_initialized=True)

    assert change is not None
    assert change.event_type is EventType.NEW_TITLE
    assert change.source_event_id == "v30000:NEW_TITLE"


def test_tba_to_concrete_date_emits_stable_release_date_event() -> None:
    previous = snapshot_from_event(load_fixture("tba"), observed_at=OBSERVED_AT)
    current = load_fixture("future")

    change = detect_change(previous, current, baseline_initialized=True)
    repeated = detect_change(previous, current, baseline_initialized=True)

    assert change is not None
    assert change.event_type is EventType.RELEASE_DATE
    assert change.source_event_id == "v20431:RELEASE_DATE:2026-09-25"
    assert repeated is not None
    assert repeated.source_event_id == change.source_event_id


def test_later_date_emits_delay_with_previous_and_new_dates() -> None:
    previous = snapshot_from_event(load_fixture("future"), observed_at=OBSERVED_AT)
    current = load_fixture("delayed")

    change = detect_change(previous, current, baseline_initialized=True)

    assert change is not None
    assert change.event_type is EventType.DELAY
    assert change.source_event_id == "v20431:DELAY:2026-09-25->2026-11-27"
    assert change.metadata["previous_release_date"] == "2026-09-25"
    assert change.metadata["new_release_date"] == "2026-11-27"


def test_earlier_date_change_emits_delay_with_previous_and_new_dates() -> None:
    previous = snapshot_from_event(load_fixture("delayed"), observed_at=OBSERVED_AT)
    current = load_fixture("future")

    change = detect_change(previous, current, baseline_initialized=True)

    assert change is not None
    assert change.event_type is EventType.DELAY
    assert change.source_event_id == "v20431:DELAY:2026-11-27->2026-09-25"
    assert change.metadata["previous_release_date"] == "2026-11-27"
    assert change.metadata["new_release_date"] == "2026-09-25"


def test_unchanged_state_emits_no_event() -> None:
    current = load_fixture("future")
    previous = snapshot_from_event(current, observed_at=OBSERVED_AT)

    assert detect_change(previous, current, baseline_initialized=True) is None


def test_unreleased_to_released_emits_released_once() -> None:
    previous = snapshot_from_event(load_fixture("future"), observed_at=OBSERVED_AT)
    current = load_fixture("released")

    change = detect_change(previous, current, baseline_initialized=True)
    repeated = detect_change(
        snapshot_from_event(current, observed_at=OBSERVED_AT),
        current,
        baseline_initialized=True,
    )

    assert change is not None
    assert change.event_type is EventType.RELEASED
    assert change.source_event_id == "v20431:RELEASED:2026-09-25"
    assert repeated is None


def test_snapshot_state_round_trips_and_baseline_mark_is_idempotent(event_store) -> None:
    current = load_fixture("future")
    snapshot = snapshot_from_event(current, observed_at=OBSERVED_AT)

    assert isinstance(snapshot, SourceSnapshotState)
    assert event_store.get_snapshot("vndb", snapshot.entity_key) is None
    assert event_store.is_baseline_initialized("vndb") is False

    event_store.save_snapshot("vndb", snapshot)
    event_store.mark_baseline_initialized("vndb", initialized_at=OBSERVED_AT)
    event_store.mark_baseline_initialized("vndb", initialized_at=datetime(2026, 8, 17, tzinfo=UTC))

    loaded = event_store.get_snapshot("vndb", snapshot.entity_key)
    assert loaded == snapshot
    assert event_store.is_baseline_initialized("vndb") is True


def test_initialize_migrates_existing_events_without_deleting_rows(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE events ("
                "id INTEGER PRIMARY KEY, "
                "source TEXT NOT NULL, "
                "source_event_id TEXT NOT NULL"
                ")"
            )
        )
        connection.execute(
            text("INSERT INTO events (id, source, source_event_id) VALUES (1, 'vndb', 'legacy-1')")
        )

    store = EventStore(database_url)
    store.initialize()
    store.initialize()

    columns = {column["name"] for column in inspect(store.engine).get_columns("events")}
    with store.engine.connect() as connection:
        legacy_row = connection.execute(text("SELECT id FROM events WHERE id = 1")).one()

    assert "image_url" in columns
    assert {"source_snapshots", "source_baselines"}.issubset(
        inspect(store.engine).get_table_names()
    )
    assert legacy_row.id == 1
