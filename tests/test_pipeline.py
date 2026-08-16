from __future__ import annotations

import asyncio
import json
from pathlib import Path

from gal_radar.config import AppConfig
from gal_radar.models.event import EventType, NotificationStatus, SourceEvent
from gal_radar.services.normalize import normalize_event
from gal_radar.services.pipeline import Pipeline
from gal_radar.services.ranking import score_event

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "change_detection"


class SequenceAdapter:
    name = "vndb"

    def __init__(self, *runs: list[SourceEvent]) -> None:
        self._runs = runs
        self._index = 0

    async def fetch_events(self, follow):
        run = self._runs[min(self._index, len(self._runs) - 1)]
        self._index += 1
        return list(run)


class SuccessfulNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, message: str) -> bool:
        self.messages.append(message)
        return True


class FailingOnceNotifier(SuccessfulNotifier):
    def __init__(self) -> None:
        super().__init__()
        self.failed = True

    async def send(self, message: str) -> bool:
        if self.failed:
            self.failed = False
            raise RuntimeError("Telegram unavailable")
        return await super().send(message)


class DryRunNotifier(SuccessfulNotifier):
    async def send(self, message: str) -> bool:
        self.messages.append(message)
        return False


def load_fixture(name: str) -> SourceEvent:
    payload = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return SourceEvent.model_validate(payload)


def low_threshold_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "follow": {"visual_novels": ["v20431"], "developers": ["枕"]},
            "notification": {"immediate_threshold": 70, "digest_threshold": 40},
        }
    )


def quiet_config() -> AppConfig:
    return AppConfig.model_validate(
        {"notification": {"immediate_threshold": 70, "digest_threshold": 40}}
    )


def test_first_run_establishes_baseline_without_historical_notification(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        pipeline = Pipeline(
            config=low_threshold_config(),
            store=event_store,
            adapters=[SequenceAdapter([load_fixture("future")])],
            notifier=notifier,
        )

        processed = await pipeline.run()

        assert processed == []
        assert event_store.list_events() == []
        assert notifier.messages == []
        assert event_store.is_baseline_initialized("vndb") is True
        assert event_store.get_snapshot("vndb", "v20431") is not None

    asyncio.run(run())


def test_release_date_change_is_notified_once_and_unchanged_state_is_silent(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        pipeline = Pipeline(
            config=low_threshold_config(),
            store=event_store,
            adapters=[
                SequenceAdapter(
                    [load_fixture("future")],
                    [load_fixture("delayed")],
                    [load_fixture("delayed")],
                )
            ],
            notifier=notifier,
        )

        await pipeline.run()
        changed = await pipeline.run()
        unchanged = await pipeline.run()

        assert len(changed) == 1
        assert changed[0].event_type == EventType.DELAY.value
        assert changed[0].metadata_json["previous_release_date"] == "2026-09-25"
        assert changed[0].metadata_json["new_release_date"] == "2026-11-27"
        assert unchanged == []
        assert len(event_store.list_events()) == 1
        assert len(notifier.messages) == 1

    asyncio.run(run())


def test_tba_to_date_emits_release_date_and_advances_snapshot(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        pipeline = Pipeline(
            config=low_threshold_config(),
            store=event_store,
            adapters=[
                SequenceAdapter(
                    [load_fixture("tba")],
                    [load_fixture("future")],
                    [load_fixture("future")],
                )
            ],
            notifier=notifier,
        )

        await pipeline.run()
        changed = await pipeline.run()
        unchanged = await pipeline.run()

        assert changed[0].event_type == EventType.RELEASE_DATE.value
        assert changed[0].source_event_id == "v20431:RELEASE_DATE:2026-09-25"
        assert unchanged == []
        assert len(event_store.list_events()) == 1
        snapshot = event_store.get_snapshot("vndb", "v20431")
        assert snapshot is not None
        assert snapshot.release_date.isoformat() == "2026-09-25"

    asyncio.run(run())


def test_unreleased_to_released_is_notified_once(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        pipeline = Pipeline(
            config=low_threshold_config(),
            store=event_store,
            adapters=[
                SequenceAdapter(
                    [load_fixture("future")],
                    [load_fixture("released")],
                    [load_fixture("released")],
                )
            ],
            notifier=notifier,
        )

        await pipeline.run()
        first_release = await pipeline.run()
        second_release = await pipeline.run()

        assert len(first_release) == 1
        assert first_release[0].event_type == EventType.RELEASED.value
        assert second_release == []
        assert len(notifier.messages) == 1

    asyncio.run(run())


def test_new_title_after_baseline_creates_event_without_historical_backfill(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        pipeline = Pipeline(
            config=low_threshold_config(),
            store=event_store,
            adapters=[SequenceAdapter([load_fixture("future")], [load_fixture("new_title")])],
            notifier=notifier,
        )

        await pipeline.run()
        new_title = await pipeline.run()

        assert len(new_title) == 1
        assert new_title[0].event_type == EventType.NEW_TITLE.value
        assert new_title[0].notification_status == NotificationStatus.SENT.value
        assert len(notifier.messages) == 1
        assert event_store.get_snapshot("vndb", "v30000") is not None

    asyncio.run(run())


def test_skipped_transition_advances_snapshot_without_notification(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        pipeline = Pipeline(
            config=quiet_config(),
            store=event_store,
            adapters=[SequenceAdapter([load_fixture("tba")], [load_fixture("future")])],
            notifier=notifier,
        )

        await pipeline.run()
        skipped = await pipeline.run()

        assert skipped[0].event_type == EventType.RELEASE_DATE.value
        assert skipped[0].notification_status == NotificationStatus.SKIPPED.value
        assert notifier.messages == []
        snapshot = event_store.get_snapshot("vndb", "v20431")
        assert snapshot is not None
        assert snapshot.release_date.isoformat() == "2026-09-25"

    asyncio.run(run())


def test_digest_transition_advances_snapshot_without_notification(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        pipeline = Pipeline(
            config=quiet_config(),
            store=event_store,
            adapters=[SequenceAdapter([load_fixture("future")], [load_fixture("new_title")])],
            notifier=notifier,
        )

        await pipeline.run()
        digest = await pipeline.run()

        assert digest[0].event_type == EventType.NEW_TITLE.value
        assert digest[0].notification_status == NotificationStatus.DIGEST.value
        assert notifier.messages == []
        assert event_store.get_snapshot("vndb", "v30000") is not None

    asyncio.run(run())


def test_already_sent_duplicate_still_advances_stale_snapshot(event_store) -> None:
    async def run() -> None:
        config = low_threshold_config()
        existing = normalize_event(load_fixture("future"))
        record = event_store.add(existing, score_event(existing, config))
        event_store.update_notification_status(record.id, NotificationStatus.SENT)
        notifier = SuccessfulNotifier()
        pipeline = Pipeline(
            config=config,
            store=event_store,
            adapters=[SequenceAdapter([load_fixture("tba")], [load_fixture("future")])],
            notifier=notifier,
        )

        await pipeline.run()
        processed = await pipeline.run()

        assert processed == []
        assert notifier.messages == []
        snapshot = event_store.get_snapshot("vndb", "v20431")
        assert snapshot is not None
        assert snapshot.release_date.isoformat() == "2026-09-25"

    asyncio.run(run())


def test_delivery_failure_keeps_previous_snapshot_and_retries_same_transition(event_store) -> None:
    async def run() -> None:
        notifier = FailingOnceNotifier()
        pipeline = Pipeline(
            config=low_threshold_config(),
            store=event_store,
            adapters=[
                SequenceAdapter(
                    [load_fixture("future")],
                    [load_fixture("delayed")],
                    [load_fixture("delayed")],
                )
            ],
            notifier=notifier,
        )

        await pipeline.run()
        failed = await pipeline.run()
        retried = await pipeline.run()

        assert failed[0].notification_status == NotificationStatus.FAILED.value
        assert retried[0].notification_status == NotificationStatus.SENT.value
        assert len(event_store.list_events()) == 1
        snapshot = event_store.get_snapshot("vndb", "v20431")
        assert snapshot is not None
        assert snapshot.release_date.isoformat() == "2026-11-27"
        assert len(notifier.messages) == 1

    asyncio.run(run())


def test_dry_run_does_not_advance_snapshot_or_mark_event_delivered(event_store) -> None:
    async def run() -> None:
        notifier = DryRunNotifier()
        pipeline = Pipeline(
            config=low_threshold_config(),
            store=event_store,
            adapters=[
                SequenceAdapter(
                    [load_fixture("future")],
                    [load_fixture("delayed")],
                )
            ],
            notifier=notifier,
        )

        await pipeline.run()
        pending = await pipeline.run()
        retried = await pipeline.run()

        assert pending[0].notification_status == NotificationStatus.PENDING.value
        assert retried[0].notification_status == NotificationStatus.PENDING.value
        assert len(event_store.list_events()) == 1
        assert len(notifier.messages) == 2
        snapshot = event_store.get_snapshot("vndb", "v20431")
        assert snapshot is not None
        assert snapshot.release_date.isoformat() == "2026-09-25"

    asyncio.run(run())
