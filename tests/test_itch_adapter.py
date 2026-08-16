from __future__ import annotations

import asyncio
import hashlib

import httpx

from gal_radar.adapters.itch import ItchAdapter
from gal_radar.config import FollowConfig, ItchAppConfig
from gal_radar.models.event import EventType


def _follow() -> FollowConfig:
    return FollowConfig(
        itch_apps=[
            ItchAppConfig(
                url="https://example.itch.io/game",
                developer="Example Dev",
                vn_id="v20431",
            )
        ]
    )


def test_itch_is_normalized_into_source_event() -> None:
    async def run() -> None:
        feed_xml = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
<channel>
  <title>Example Feed</title>
  <link>https://example.itch.io/game/devlog</link>
  <description>Example Feed Description</description>
  <item>
    <title>Release Date Announced: October 30, 2026</title>
    <link>https://example.itch.io/game/devlog/999/update</link>
    <description>The release date is October 30, 2026.</description>
    <guid>999</guid>
    <pubDate>Mon, 10 Aug 2026 00:00:00 GMT</pubDate>
  </item>
</channel>
</rss>"""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert str(request.url) == "https://example.itch.io/game/devlog.rss"
            return httpx.Response(200, content=feed_xml.encode(), request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await ItchAdapter(client).fetch_events(_follow())

        assert len(events) == 1
        event = events[0]
        assert event.source == "itch.io"
        feed_hash = hashlib.md5(b"https://example.itch.io/game").hexdigest()[:8]
        assert event.source_event_id == f"{feed_hash}:999"
        assert event.vn_id == "v20431"
        assert event.event_type is EventType.RELEASE_DATE
        assert event.title == "Release Date Announced: October 30, 2026"
        assert event.developer_names == ["Example Dev"]
        assert event.metadata["feed_url"] == "https://example.itch.io/game/devlog.rss"
        assert event.metadata["rss_guid"] == "999"
        assert event.metadata["feed_key"] == "itch:https://example.itch.io/game"
        assert event.metadata["release_date"] == "2026-10-30"

    asyncio.run(run())


def test_itch_missing_guid_falls_back_to_link() -> None:
    async def run() -> None:
        feed_xml = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
<channel>
  <item>
    <title>News item</title>
    <link>https://example.itch.io/game/devlog/123/news</link>
  </item>
</channel>
</rss>"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=feed_xml.encode(), request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await ItchAdapter(client).fetch_events(_follow())

        assert len(events) == 1
        assert events[0].metadata["rss_guid"] == "https://example.itch.io/game/devlog/123/news"

    asyncio.run(run())


def test_itch_timeout_is_wrapped() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await ItchAdapter(client).fetch_events(_follow())
            assert events == []

    asyncio.run(run())


def test_itch_http_error_is_wrapped() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, content=b"Server error", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await ItchAdapter(client).fetch_events(_follow())
            assert events == []

    asyncio.run(run())


def test_itch_malformed_feed_is_wrapped() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            # Completely invalid XML that feedparser bozo will reject
            return httpx.Response(200, content=b"\x00\x01\x02\x03", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await ItchAdapter(client).fetch_events(_follow())
            assert events == []

    asyncio.run(run())


def test_itch_feed_failure_isolates_error() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "fail" in str(request.url):
                raise httpx.ReadTimeout("timeout", request=request)
            feed_xml = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
<channel>
  <item>
    <title>News item</title>
    <link>https://example.itch.io/success/devlog/123/news</link>
  </item>
</channel>
</rss>"""
            return httpx.Response(200, content=feed_xml.encode(), request=request)

        follow = FollowConfig(
            itch_apps=[
                ItchAppConfig(url="https://example.itch.io/fail", vn_id="v1"),
                ItchAppConfig(url="https://example.itch.io/success", vn_id="v2"),
            ]
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await ItchAdapter(client).fetch_events(follow)
            assert len(events) == 1
            assert events[0].vn_id == "v2"

    asyncio.run(run())
