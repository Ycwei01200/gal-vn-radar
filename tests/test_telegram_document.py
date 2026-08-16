from __future__ import annotations

import asyncio
import json

import httpx

from gal_radar.notifications.telegram import TelegramNotifier

IMAGE_URL = "https://t.vndb.org/cv/12/3456.jpg"


def test_telegram_document_mode_uses_send_document() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"ok": True}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(
                bot_token="token",
                chat_id="123",
                client=client,
                image_delivery="document",
            )
            assert await notifier.send("message", image_url=IMAGE_URL) is True

        assert len(requests) == 1
        assert requests[0].url.path.endswith("/sendDocument")
        assert json.loads(requests[0].content) == {
            "chat_id": "123",
            "document": IMAGE_URL,
            "caption": "message",
        }

    asyncio.run(run())


def test_telegram_document_failure_falls_back_to_photo() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/sendDocument"):
                return httpx.Response(500, json={"ok": False}, request=request)
            return httpx.Response(200, json={"ok": True}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(
                bot_token="token",
                chat_id="123",
                client=client,
                image_delivery="document",
            )
            assert await notifier.send("message", image_url=IMAGE_URL) is True

        assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
            "sendDocument",
            "sendPhoto",
        ]

    asyncio.run(run())
