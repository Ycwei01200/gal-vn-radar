from __future__ import annotations

import asyncio

from gal_radar.models.event import EventType, NotificationStatus, SourceEvent
from gal_radar.services.pipeline import Pipeline


class StaticAdapter:
    name = "fixture"

    def __init__(self, events):
        self._events = events

    async def fetch_events(self, follow):
        return list(self._events)


class SuccessfulNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, message: str) -> bool:
        self.messages.append(message)
        return True


class FailingNotifier:
    async def send(self, message: str) -> bool:
        raise RuntimeError("Telegram unavailable")


class DryRunNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, message: str) -> bool:
        self.messages.append(message)
        return False


def high_score_event() -> SourceEvent:
    return SourceEvent(
        source="vndb",
        source_event_id="v20431:RELEASE_DATE:2026-10-30",
        vn_id="v20431",
        developer_names=["枕"],
        tags=["nakige"],
        event_type=EventType.RELEASE_DATE,
        title="サクラノ刻",
        url="https://vndb.org/v20431",
        metadata={"release_date": "2026-10-30"},
    )


def test_rerunning_same_pipeline_does_not_send_duplicate(app_config, event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        pipeline = Pipeline(
            config=app_config,
            store=event_store,
            adapters=[StaticAdapter([high_score_event()])],
            notifier=notifier,
        )

        await pipeline.run()
        await pipeline.run()

        assert len(event_store.list_events()) == 1
        assert len(notifier.messages) == 1
        assert event_store.list_events()[0].notification_status == NotificationStatus.SENT.value

    asyncio.run(run())


def test_delivery_failure_does_not_mark_event_sent(app_config, event_store) -> None:
    async def run() -> None:
        pipeline = Pipeline(
            config=app_config,
            store=event_store,
            adapters=[StaticAdapter([high_score_event()])],
            notifier=FailingNotifier(),
        )

        await pipeline.run()

        record = event_store.list_events()[0]
        assert record.notification_status == NotificationStatus.FAILED.value

    asyncio.run(run())


def test_dry_run_does_not_mark_event_delivered(app_config, event_store) -> None:
    async def run() -> None:
        notifier = DryRunNotifier()
        pipeline = Pipeline(
            config=app_config,
            store=event_store,
            adapters=[StaticAdapter([high_score_event()])],
            notifier=notifier,
        )

        await pipeline.run()

        record = event_store.list_events()[0]
        assert len(notifier.messages) == 1
        assert record.notification_status == NotificationStatus.PENDING.value

    asyncio.run(run())
