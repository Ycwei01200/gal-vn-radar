from __future__ import annotations

import asyncio

import httpx
import pytest

from gal_radar.adapters.rss import RSSAdapter
from gal_radar.config import FeedConfig, FollowConfig
from gal_radar.services.http_safety import (
    ResponseTooLargeError,
    UnsafeUrlError,
    fetch_limited_bytes,
    safe_url_for_log,
    validate_public_http_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/feed.xml",
        "http://10.0.0.1/feed.xml",
        "http://192.168.1.2/feed.xml",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/feed.xml",
        "http://localhost/feed.xml",
        "http://service.local/feed.xml",
        "file:///etc/passwd",
        "https://user:secret@example.com/feed.xml",
    ],
)
def test_validate_public_http_url_rejects_local_and_credentialed_targets(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_http_url(url)


def test_validate_public_http_url_accepts_normal_public_https_url() -> None:
    assert (
        validate_public_http_url("https://example.com/news/feed.xml")
        == "https://example.com/news/feed.xml"
    )


def test_safe_url_for_log_removes_credentials_query_and_fragment() -> None:
    value = "https://user:secret@example.com/feed.xml?token=top-secret#section"
    assert safe_url_for_log(value) == "https://example.com/feed.xml"


def test_redirect_to_private_address_is_rejected_before_second_request() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/admin"},
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(UnsafeUrlError):
                await fetch_limited_bytes(
                    client,
                    "https://example.com/feed.xml",
                    timeout=5.0,
                    max_bytes=1024,
                )

        assert len(requests) == 1
        assert requests[0].url.host == "example.com"

    asyncio.run(run())


def test_response_size_limit_rejects_oversized_body() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 2048, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ResponseTooLargeError):
                await fetch_limited_bytes(
                    client,
                    "https://example.com/feed.xml",
                    timeout=5.0,
                    max_bytes=1024,
                )

    asyncio.run(run())


def test_rss_adapter_does_not_request_private_manual_feed() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=b"<rss/>", request=request)

        follow = FollowConfig(
            feeds=[
                FeedConfig(
                    url="http://127.0.0.1/feed.xml",
                    vn_id="v1",
                )
            ]
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await RSSAdapter(client).fetch_events(follow)

        assert events == []
        assert requests == []

    asyncio.run(run())
