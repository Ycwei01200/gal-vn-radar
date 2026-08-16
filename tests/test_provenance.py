import asyncio
from datetime import UTC, datetime

from gal_radar.config import AppConfig
from gal_radar.database import EventStore
from gal_radar.models.event import EventType, SourceEvent
from gal_radar.notifications.base import NotificationSink
from gal_radar.services.pipeline import Pipeline


class DummyNotifier(NotificationSink):
    async def send(self, message: str, *, image_url: str | None = None) -> bool:
        return True


class DummyAdapter:
    mode = "feed"

    def __init__(self, name: str, events: list[SourceEvent]) -> None:
        self.name = name
        self._events = events

    async def fetch_events(self, follow):
        return self._events


def _event(
    source: str, source_event_id: str, title: str, event_type: EventType, url: str
) -> SourceEvent:
    return SourceEvent(
        source=source,
        source_event_id=source_event_id,
        vn_id="v1",
        developer_names=[],
        tags=[],
        event_type=event_type,
        title=title,
        summary="summary",
        url=url,
        published_at=datetime.now(UTC),
        metadata={},
    )


def test_provenance_merges_across_sources_idempotently() -> None:
    async def run() -> None:
        store = EventStore("sqlite:///:memory:")
        store.initialize()
        store.mark_baseline_initialized("vndb")
        store.mark_baseline_initialized("steam")
        store.mark_baseline_initialized("rss")
        
        config = AppConfig.model_validate(
            {"notification": {"immediate_threshold": 70, "digest_threshold": 40}}
        )

        vndb_event = _event("vndb", "v1:RELEASED:2026-01-01", "Game", EventType.RELEASED, "http://vndb")
        steam_event = _event("steam", "123:456", "Now Available", EventType.RELEASED, "http://steam")
        rss_event = _event("rss", "rss:789", "Game out now", EventType.RELEASED, "http://rss")

        # Step 1: VNDB event comes in
        pipeline_vndb = Pipeline(
            config=config,
            store=store,
            adapters=[DummyAdapter("vndb", [vndb_event])],
            notifier=DummyNotifier(),
        )
        await pipeline_vndb.run()

        events = store.list_events()
        assert len(events) == 1
        assert events[0].source == "vndb"
        assert len(events[0].corroborating_sources) == 0

        # Step 2: Steam event comes in (duplicate logical event)
        pipeline_steam = Pipeline(
            config=config,
            store=store,
            adapters=[DummyAdapter("steam", [steam_event])],
            notifier=DummyNotifier(),
        )
        await pipeline_steam.run()

        events = store.list_events()
        assert len(events) == 1
        assert len(events[0].corroborating_sources) == 1
        assert events[0].corroborating_sources[0]["source"] == "steam"
        assert events[0].corroborating_sources[0]["url"] == "http://steam/"

        # Step 3: RSS event comes in
        pipeline_rss = Pipeline(
            config=config,
            store=store,
            adapters=[DummyAdapter("rss", [rss_event])],
            notifier=DummyNotifier(),
        )
        await pipeline_rss.run()

        events = store.list_events()
        assert len(events) == 1
        assert len(events[0].corroborating_sources) == 2
        assert events[0].corroborating_sources[1]["source"] == "rss"

        # Step 4: Steam event comes in again (idempotent)
        await pipeline_steam.run()
        events = store.list_events()
        assert len(events) == 1
        assert len(events[0].corroborating_sources) == 2

        # Step 5: A totally different logical event does NOT merge
        other_event = _event("vndb", "v2:NEW_TITLE", "Game 2", EventType.NEW_TITLE, "http://vndb2")
        pipeline_other = Pipeline(
            config=config,
            store=store,
            adapters=[DummyAdapter("vndb", [other_event])],
            notifier=DummyNotifier(),
        )
        await pipeline_other.run()

        events = store.list_events()
        assert len(events) == 2

    asyncio.run(run())
