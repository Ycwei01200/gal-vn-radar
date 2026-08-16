from __future__ import annotations

import asyncio
import hashlib

import httpx
import pytest

from gal_radar.adapters.base import SourceAdapterError
from gal_radar.adapters.rss import RSSAdapter
from gal_radar.config import FeedConfig, FollowConfig
from gal_radar.models.event import EventType


def _follow() -> FollowConfig:
    return FollowConfig(
        feeds=[
            FeedConfig(
                url="https://example.com/rss.xml",
                developer="Makura",
                vn_id="v20431",
            )
        ]
    )


def test_rss_is_normalized_into_source_event() -> None:
    async def run() -> None:
        feed_xml = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
<channel>
  <title>Example Feed</title>
  <link>https://example.com/</link>
  <description>Example Feed Description</description>
  <item>
    <title>Release Date Announced: October 30, 2026</title>
    <link>https://example.com/news/999</link>
    <description>The release date is October 30, 2026.</description>
    <guid>999</guid>
    <pubDate>Mon, 10 Aug 2026 00:00:00 GMT</pubDate>
  </item>
</channel>
</rss>"""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert str(request.url) == "https://example.com/rss.xml"
            return httpx.Response(200, content=feed_xml.encode(), request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await RSSAdapter(client).fetch_events(_follow())

        assert len(events) == 1
        event = events[0]
        assert event.source == "rss"
        feed_hash = hashlib.md5(b"https://example.com/rss.xml").hexdigest()[:8]
        assert event.source_event_id == f"{feed_hash}:999"
        assert event.vn_id == "v20431"
        assert event.event_type is EventType.RELEASE_DATE
        assert event.title == "Release Date Announced: October 30, 2026"
        assert event.developer_names == ["Makura"]
        assert event.metadata["feed_url"] == "https://example.com/rss.xml"
        assert event.metadata["rss_guid"] == "999"
        assert event.metadata["feed_key"] == "rss:https://example.com/rss.xml"
        assert event.metadata["release_date"] == "2026-10-30"

    asyncio.run(run())


def test_missing_guid_falls_back_to_link() -> None:
    async def run() -> None:
        feed_xml = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
<channel>
  <item>
    <title>News item</title>
    <link>https://example.com/news/123</link>
  </item>
</channel>
</rss>"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=feed_xml.encode(), request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await RSSAdapter(client).fetch_events(_follow())

        assert len(events) == 1
        assert events[0].metadata["rss_guid"] == "https://example.com/news/123"

    asyncio.run(run())


def test_rss_timeout_is_wrapped() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(SourceAdapterError, match="timed out"):
                await RSSAdapter(client).fetch_events(_follow())

    asyncio.run(run())


def test_rss_http_error_is_wrapped() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, content=b"Server error", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(SourceAdapterError, match="failed for"):
                await RSSAdapter(client).fetch_events(_follow())

    asyncio.run(run())


def test_malformed_feed_is_wrapped() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            # Completely invalid XML that feedparser bozo will reject
            return httpx.Response(200, content=b"\x00\x01\x02\x03", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(SourceAdapterError, match="Malformed feed"):
                await RSSAdapter(client).fetch_events(_follow())

    asyncio.run(run())
