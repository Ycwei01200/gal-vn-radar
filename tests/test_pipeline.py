from __future__ import annotations

import asyncio

from gal_radar.config import AppConfig
from gal_radar.models.event import EventType, NotificationStatus, SourceEvent
from gal_radar.services.pipeline import Pipeline


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


def event(
    *,
    vn_id: str = "v20431",
    title: str = "サクラノ刻",
    release_date: str | None = "2026-10-30",
    event_type: EventType = EventType.RELEASE_DATE,
    release_state: str = "unreleased",
) -> SourceEvent:
    metadata = {"release_state": release_state}
    if release_date is not None:
        metadata["release_date"] = release_date
    return SourceEvent(
        source="vndb",
        source_event_id=f"{vn_id}:{event_type.value}:{release_date or 'TBA'}",
        vn_id=vn_id,
        developer_names=["枕"],
        tags=["nakige"],
        event_type=event_type,
        title=title,
        url=f"https://vndb.org/{vn_id}",
        metadata=metadata,
    )


def low_threshold_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "follow": {"visual_novels": ["v20431"], "developers": ["枕"]},
            "notification": {"immediate_threshold": 70, "digest_threshold": 40},
        }
    )


def test_first_run_establishes_baseline_without_historical_notification(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        pipeline = Pipeline(
            config=low_threshold_config(),
            store=event_store,
            adapters=[SequenceAdapter([event()])],
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
                    [event(release_date="2026-10-30")],
                    [event(release_date="2026-11-27")],
                    [event(release_date="2026-11-27")],
                )
            ],
            notifier=notifier,
        )

        await pipeline.run()
        changed = await pipeline.run()
        unchanged = await pipeline.run()

        assert len(changed) == 1
        assert changed[0].event_type == EventType.DELAY.value
        assert changed[0].metadata_json["previous_release_date"] == "2026-10-30"
        assert changed[0].metadata_json["new_release_date"] == "2026-11-27"
        assert unchanged == []
        assert len(event_store.list_events()) == 1
        assert len(notifier.messages) == 1

    asyncio.run(run())


def test_unreleased_to_released_is_notified_once(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        pipeline = Pipeline(
            config=low_threshold_config(),
            store=event_store,
            adapters=[
                SequenceAdapter(
                    [event()],
                    [event(event_type=EventType.RELEASED, release_state="released")],
                    [event(event_type=EventType.RELEASED, release_state="released")],
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
            adapters=[SequenceAdapter([event()], [event(vn_id="v30000", title="新作")])],
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


def test_delivery_failure_keeps_previous_snapshot_and_retries_same_transition(event_store) -> None:
    async def run() -> None:
        notifier = FailingOnceNotifier()
        pipeline = Pipeline(
            config=low_threshold_config(),
            store=event_store,
            adapters=[
                SequenceAdapter(
                    [event(release_date="2026-10-30")],
                    [event(release_date="2026-11-27")],
                    [event(release_date="2026-11-27")],
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
                    [event(release_date="2026-10-30")],
                    [event(release_date="2026-11-27")],
                )
            ],
            notifier=notifier,
        )

        await pipeline.run()
        pending = await pipeline.run()

        assert pending[0].notification_status == NotificationStatus.PENDING.value
        assert len(notifier.messages) == 1
        snapshot = event_store.get_snapshot("vndb", "v20431")
        assert snapshot is not None
        assert snapshot.release_date.isoformat() == "2026-10-30"

    asyncio.run(run())
