from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from gal_radar.config import AppConfig
from gal_radar.models.event import EventType, NotificationStatus, SourceEvent
from gal_radar.services.pipeline import Pipeline


class FeedSequenceAdapter:
    name = "steam"
    mode = "feed"

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

    async def send(self, message: str, *, image_url: str | None = None) -> bool:
        self.messages.append(message)
        return True


def _event(gid: str, *, event_type: EventType = EventType.PATCH) -> SourceEvent:
    return SourceEvent(
        source="steam",
        source_event_id=f"123456:{gid}",
        vn_id="v20431",
        developer_names=["枕"],
        event_type=event_type,
        title="サクラノ刻－櫻の森の下を歩む－",
        summary=f"Steam item {gid}",
        url=f"https://store.steampowered.com/news/app/123456/view/{gid}",
        published_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        metadata={
            "steam_app_id": 123456,
            "steam_gid": gid,
            "news_title": f"Patch {gid}",
            "feed_key": "steam:123456",
        },
    )


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "follow": {
                "developers": ["枕"],
                "visual_novels": ["v20431"],
                "steam_apps": [
                    {
                        "app_id": 123456,
                        "vn_id": "v20431",
                        "title": "サクラノ刻－櫻の森の下を歩む－",
                        "developer": "枕",
                    }
                ],
            },
            "notification": {"immediate_threshold": 70, "digest_threshold": 40},
        }
    )


def test_first_steam_feed_run_is_silent_and_marks_items_seen(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        old = [_event("1"), _event("2")]
        pipeline = Pipeline(
            config=_config(),
            store=event_store,
            adapters=[FeedSequenceAdapter(old, old)],
            notifier=notifier,
        )

        first = await pipeline.run()
        second = await pipeline.run()

        assert first == []
        assert second == []
        assert notifier.messages == []
        assert event_store.list_events() == []
        assert event_store.is_baseline_initialized("steam:123456") is True
        assert event_store.is_source_item_seen("steam", "123456:1") is True
        assert event_store.is_source_item_seen("steam", "123456:2") is True

    asyncio.run(run())


def test_new_steam_item_after_baseline_is_processed_once(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        old = [_event("1")]
        updated = [_event("2"), _event("1")]
        pipeline = Pipeline(
            config=_config(),
            store=event_store,
            adapters=[FeedSequenceAdapter(old, updated, updated)],
            notifier=notifier,
        )

        await pipeline.run()
        new_items = await pipeline.run()
        repeated = await pipeline.run()

        assert len(new_items) == 1
        assert new_items[0].source == "steam"
        assert new_items[0].source_event_id == "123456:2"
        assert new_items[0].notification_status == NotificationStatus.SENT.value
        assert repeated == []
        assert len(notifier.messages) == 1
        assert event_store.is_source_item_seen("steam", "123456:2") is True

    asyncio.run(run())


def test_newly_added_steam_app_gets_its_own_silent_baseline(event_store) -> None:
    async def run() -> None:
        notifier = SuccessfulNotifier()
        app_one = _event("1")
        app_two = SourceEvent(
            source="steam",
            source_event_id="654321:9",
            vn_id="v30000",
            event_type=EventType.OTHER,
            title="Second VN",
            summary="Historical announcement",
            url="https://store.steampowered.com/news/app/654321/view/9",
            metadata={
                "steam_app_id": 654321,
                "steam_gid": "9",
                "news_title": "Old announcement",
                "feed_key": "steam:654321",
            },
        )
        pipeline = Pipeline(
            config=_config(),
            store=event_store,
            adapters=[FeedSequenceAdapter([app_one], [app_one, app_two])],
            notifier=notifier,
        )

        await pipeline.run()
        result = await pipeline.run()

        assert result == []
        assert notifier.messages == []
        assert event_store.is_baseline_initialized("steam:654321") is True
        assert event_store.is_source_item_seen("steam", "654321:9") is True

    asyncio.run(run())
