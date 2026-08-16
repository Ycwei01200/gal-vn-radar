from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest

from gal_radar.adapters.base import SourceAdapterError
from gal_radar.adapters.vndb import VNDBAdapter
from gal_radar.config import FollowConfig
from gal_radar.models.event import EventType


def test_vndb_response_is_normalized_into_source_event() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/vn")
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "v20431",
                            "title": "Sakura no Toki",
                            "alttitle": "サクラノ刻",
                            "released": "2026-10-30",
                            "developers": [{"id": "p30", "name": "枕"}],
                            "tags": [{"id": "g596", "name": "nakige"}],
                        }
                    ],
                    "more": False,
                },
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = VNDBAdapter(
                client,
                now=lambda: datetime(2026, 8, 16, tzinfo=UTC),
            )
            events = await adapter.fetch_events(FollowConfig(visual_novels=["v20431"]))

        assert len(events) == 1
        event = events[0]
        assert event.source == "vndb"
        assert event.source_event_id == "v20431:RELEASE_DATE:2026-10-30"
        assert event.event_type is EventType.RELEASE_DATE
        assert event.title == "サクラノ刻"
        assert event.developer_names == ["枕"]
        assert event.tags == ["nakige"]
        assert event.metadata["release_date"] == "2026-10-30"

    asyncio.run(run())


def test_vndb_developer_name_is_resolved_before_querying_vns() -> None:
    async def run() -> None:
        paths: list[str] = []
        payloads: dict[str, dict[str, object]] = {}
        follow = FollowConfig(developers=["枕"])

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            payloads[request.url.path] = json.loads(request.content.decode("utf-8"))
            if request.url.path.endswith("/producer"):
                return httpx.Response(
                    200,
                    json={"results": [{"id": "p30", "name": "Makura"}]},
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "v20431",
                            "title": "Sakura no Toki",
                            "alttitle": "サクラノ刻",
                            "released": "2026-10-30",
                            "developers": [{"id": "p30", "name": "Makura"}],
                            "image": {"url": "https://t.vndb.org/cv/12/3456.jpg"},
                            "tags": [],
                        }
                    ]
                },
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await VNDBAdapter(client).fetch_events(follow)

        assert paths == ["/kana/producer", "/kana/vn"]
        assert payloads["/kana/producer"]["filters"] == ["search", "=", "枕"]
        assert payloads["/kana/vn"]["filters"] == ["developer", "=", ["id", "=", "p30"]]
        assert payloads["/kana/vn"]["fields"] == (
            "title,alttitle,released,developers{id,name},image{url},tags{id,name}"
        )
        assert follow.developers == ["枕"]
        assert follow.resolved_developer_ids == ["p30"]
        assert events[0].vn_id == "v20431"
        assert events[0].developer_id == "p30"
        assert events[0].developer_ids == ["p30"]
        assert events[0].developer_names == ["Makura"]
        assert str(events[0].image_url) == "https://t.vndb.org/cv/12/3456.jpg"

    asyncio.run(run())


def test_malformed_vndb_response_raises_source_error() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": "not-a-list"}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = VNDBAdapter(client)
            with pytest.raises(SourceAdapterError, match="Malformed VNDB /vn response"):
                await adapter.fetch_events(FollowConfig(visual_novels=["v20431"]))

    asyncio.run(run())


def test_invalid_optional_vndb_image_url_raises_source_error() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "v20431",
                            "title": "Sakura no Toki",
                            "alttitle": "サクラノ刻",
                            "released": "2026-10-30",
                            "developers": [{"id": "p30", "name": "Makura"}],
                            "image": {"url": "not-a-valid-url"},
                            "tags": [],
                        }
                    ]
                },
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = VNDBAdapter(client)
            with pytest.raises(SourceAdapterError, match="Malformed VNDB /vn response"):
                await adapter.fetch_events(FollowConfig(visual_novels=["v20431"]))

    asyncio.run(run())


def test_vndb_timeout_is_wrapped() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = VNDBAdapter(client)
            with pytest.raises(SourceAdapterError, match="timed out"):
                await adapter.fetch_events(FollowConfig(visual_novels=["v20431"]))

    asyncio.run(run())


def test_vndb_rate_limit_retries_then_succeeds() -> None:
    async def run() -> None:
        calls = 0
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "2"},
                    json={"error": "rate limited"},
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "v20431",
                            "title": "Sakura no Toki",
                            "released": "2026-10-30",
                            "developers": [],
                            "tags": [],
                        }
                    ]
                },
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = VNDBAdapter(client, sleep=fake_sleep)
            events = await adapter.fetch_events(FollowConfig(visual_novels=["v20431"]))

        assert len(events) == 1
        assert calls == 2
        assert slept == [2.0]

    asyncio.run(run())
