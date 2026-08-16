from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from gal_radar.adapters.steam import SteamNewsAdapter
from gal_radar.config import FollowConfig, SteamAppConfig
from gal_radar.models.event import EventType


def _follow() -> FollowConfig:
    return FollowConfig(
        visual_novels=["v20431"],
        steam_apps=[
            SteamAppConfig(
                app_id=123456,
                vn_id="v20431",
                title="サクラノ刻－櫻の森の下を歩む－",
                developer="枕",
            )
        ],
    )


def test_steam_news_is_normalized_into_source_event() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path.endswith("/ISteamNews/GetNewsForApp/v2/")
            assert request.url.params["appid"] == "123456"
            return httpx.Response(
                200,
                json={
                    "appnews": {
                        "appid": 123456,
                        "newsitems": [
                            {
                                "gid": "999",
                                "title": "Release Date Announced: October 30, 2026",
                                "url": "https://store.steampowered.com/news/app/123456/view/999",
                                "author": "Makura",
                                "contents": "[b]The release date is October 30, 2026.[/b]",
                                "date": 1780000000,
                                "tags": ["announcements"],
                            }
                        ],
                    }
                },
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await SteamNewsAdapter(client).fetch_events(_follow())

        assert len(events) == 1
        event = events[0]
        assert event.source == "steam"
        assert event.source_event_id == "123456:999"
        assert event.vn_id == "v20431"
        assert event.event_type is EventType.RELEASE_DATE
        assert event.title == "サクラノ刻－櫻の森の下を歩む－"
        assert event.developer_names == ["枕"]
        assert event.metadata["steam_app_id"] == 123456
        assert event.metadata["steam_gid"] == "999"
        assert event.metadata["feed_key"] == "steam:123456"
        assert event.metadata["release_date"] == "2026-10-30"
        assert "Release Date Announced" in (event.summary or "")

    asyncio.run(run())


@pytest.mark.parametrize(
    ("headline", "expected"),
    [
        ("Demo now available", EventType.DEMO),
        ("Patch 1.2 released", EventType.PATCH),
        ("Release delayed to 2026-11-27", EventType.DELAY),
        ("Official trailer", EventType.TRAILER),
        ("Now available on Steam", EventType.RELEASED),
        ("Developer update #4", EventType.DEVLOG),
        ("Community announcement", EventType.OTHER),
    ],
)
def test_steam_news_classification(headline: str, expected: EventType) -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "appnews": {
                        "appid": 123456,
                        "newsitems": [
                            {
                                "gid": "1",
                                "title": headline,
                                "url": "https://store.steampowered.com/news/app/123456/view/1",
                                "contents": "",
                                "date": 1780000000,
                            }
                        ],
                    }
                },
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            event = (await SteamNewsAdapter(client).fetch_events(_follow()))[0]
        assert event.event_type is expected

    asyncio.run(run())


def test_steam_timeout_is_wrapped() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await SteamNewsAdapter(client).fetch_events(_follow())
            assert events == []

    asyncio.run(run())


def test_malformed_steam_response_is_wrapped() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"appnews": {"appid": 123456}}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await SteamNewsAdapter(client).fetch_events(_follow())
        assert events == []

    asyncio.run(run())


def test_steam_request_uses_expected_limits() -> None:
    async def run() -> None:
        observed: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            observed.update(dict(request.url.params))
            return httpx.Response(
                200,
                content=json.dumps({"appnews": {"appid": 123456, "newsitems": []}}).encode(),
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await SteamNewsAdapter(client, count=7, max_length=600).fetch_events(_follow())

        assert observed["appid"] == "123456"
        assert observed["count"] == "7"
        assert observed["maxlength"] == "600"
        assert observed["format"] == "json"

    asyncio.run(run())


def test_steam_app_failure_isolates_error() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.params["appid"] == "123456":
                raise httpx.ReadTimeout("timeout", request=request)
            return httpx.Response(
                200,
                content=json.dumps(
                    {"appnews": {"appid": int(request.url.params["appid"]), "newsitems": []}}
                ).encode(),
                request=request,
            )

        follow = FollowConfig(
            steam_apps=[
                SteamAppConfig(app_id=123456, vn_id="v1", title="Fail App"),
                SteamAppConfig(app_id=654321, vn_id="v2", title="Success App"),
            ]
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            # Should not raise exception, should return empty list (since success app has 0 news)
            events = await SteamNewsAdapter(client).fetch_events(follow)
            assert events == []

    asyncio.run(run())
