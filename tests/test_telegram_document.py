from __future__ import annotations

import asyncio

import httpx

from gal_radar.notifications.telegram import TelegramNotifier

IMAGE_URL = "https://t.vndb.org/cv/12/3456.jpg"


def test_telegram_document_mode_uploads_original_bytes() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(
                    200,
                    content=b"original-image-bytes",
                    headers={"content-type": "image/jpeg"},
                    request=request,
                )
            return httpx.Response(200, json={"ok": True}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(
                bot_token="token",
                chat_id="123",
                client=client,
                image_delivery="document",
            )
            assert await notifier.send("message", image_url=IMAGE_URL) is True

        assert len(requests) == 2
        assert requests[0].method == "GET"
        assert str(requests[0].url) == IMAGE_URL
        assert requests[1].url.path.endswith("/sendDocument")
        assert requests[1].headers["content-type"].startswith("multipart/form-data;")
        assert b"original-image-bytes" in requests[1].content
        assert b'filename="3456.jpg"' in requests[1].content

    asyncio.run(run())


def test_telegram_document_download_failure_falls_back_to_photo() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(500, request=request)
            return httpx.Response(200, json={"ok": True}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(
                bot_token="token",
                chat_id="123",
                client=client,
                image_delivery="document",
            )
            assert await notifier.send("message", image_url=IMAGE_URL) is True

        assert requests[0].method == "GET"
        assert requests[1].url.path.endswith("/sendPhoto")

    asyncio.run(run())
