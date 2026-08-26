from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

from gal_radar.config import AppConfig
from gal_radar.models.event import EventType, SourceEvent
from gal_radar.services.pipeline import Pipeline


class FeedAdapter:
    name = "steam"
    mode = "feed"

    def __init__(self, events: list[SourceEvent]) -> None:
        self._events = events

    async def fetch_events(self, follow):
        return list(self._events)


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, message: str, *, image_url: str | None = None) -> bool:
        self.messages.append(message)
        return True


def _steam_event(*, published_at: datetime) -> SourceEvent:
    return SourceEvent(
        source="steam",
        source_event_id="123:1",
        vn_id="v50000",
        developer_id="p30",
        developer_ids=["p30"],
        developer_names=["Makura"],
        event_type=EventType.DEVLOG,
        title="Example VN",
        url="https://store.steampowered.com/news/app/123/view/1",
        published_at=published_at,
        metadata={"feed_key": "steam:123"},
    )


def test_pipeline_dry_run_does_not_initialize_feed_baseline(event_store) -> None:
    async def run() -> None:
        event = _steam_event(published_at=datetime(2026, 8, 20, tzinfo=UTC))
        pipeline = Pipeline(
            config=AppConfig(),
            store=event_store,
            adapters=[FeedAdapter([event])],
            notifier=RecordingNotifier(),
            dry_run=True,
        )

        processed = await pipeline.run()

        assert processed == []
        assert event_store.is_baseline_initialized("steam:123") is False
        assert event_store.is_source_item_seen("steam", event.source_event_id) is False
        assert event_store.list_events() == []

    asyncio.run(run())


def test_pipeline_backfill_reprocesses_seen_feed_item(event_store) -> None:
    async def run() -> None:
        event = _steam_event(published_at=datetime(2026, 8, 20, tzinfo=UTC))
        event_store.mark_baseline_initialized("steam:123")
        event_store.mark_source_item_seen("steam", event.source_event_id)

        config = AppConfig()
        config.follow.add_discovered_vn("v50000")
        pipeline = Pipeline(
            config=config,
            store=event_store,
            adapters=[FeedAdapter([event])],
            notifier=RecordingNotifier(),
            backfill_since=date(2026, 8, 16),
        )

        processed = await pipeline.run()

        assert len(processed) == 1
        assert len(event_store.list_events()) == 1

    asyncio.run(run())
