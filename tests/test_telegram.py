from __future__ import annotations

import asyncio
import json
import logging
from io import StringIO

import httpx
import pytest

from gal_radar.models.event import EventType, SourceEvent
from gal_radar.notifications.telegram import (
    TelegramDeliveryError,
    TelegramNotifier,
    render_zh_tw_notification,
)
from gal_radar.services.normalize import normalize_event
from gal_radar.services.ranking import ScoreResult

IMAGE_URL = "https://t.vndb.org/cv/12/3456.jpg"


def _record(event_store, *, image_url: str | None = None):
    event = normalize_event(
        SourceEvent(
            source="vndb",
            source_event_id="v20431:RELEASE_DATE:2026-10-30",
            vn_id="v20431",
            developer_names=["枕"],
            tags=["nakige"],
            event_type=EventType.RELEASE_DATE,
            title="サクラノ刻",
            url="https://vndb.org/v20431",
            image_url=image_url,
            metadata={"release_date": "2026-10-30"},
        )
    )
    return event_store.add(
        event,
        ScoreResult(
            score=90,
            reasons=(
                "followed developer: 枕",
                "matched tag: nakige",
                "event type: RELEASE_DATE",
            ),
        ),
    )


def test_zh_tw_rendering_uses_taiwan_traditional_chinese(event_store) -> None:
    message = render_zh_tw_notification(_record(event_store))

    assert "發售" in message
    assert "開發商" in message
    assert "你可能會感興趣" in message
    assert "你正在追蹤「枕」" in message
    assert "发行" not in message
    assert "开发商" not in message


def test_telegram_dry_run_prints_without_network(event_store) -> None:
    async def run() -> None:
        output = StringIO()

        class FailingClient:
            async def post(self, *args, **kwargs):
                raise AssertionError("Telegram network must not be called in dry-run mode")

        notifier = TelegramNotifier(dry_run=True, client=FailingClient(), stdout=output)
        message = render_zh_tw_notification(_record(event_store, image_url=IMAGE_URL))
        delivered = await notifier.send(message, image_url=IMAGE_URL)

        assert delivered is False
        assert output.getvalue() == f"{message}\n"

    asyncio.run(run())


def test_telegram_delivery_failure_is_explicit() -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"ok": False}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(bot_token="token", chat_id="123", client=client)
            with pytest.raises(TelegramDeliveryError, match="delivery request failed") as exc_info:
                await notifier.send("message")
            assert "token" not in str(exc_info.value)

    asyncio.run(run())


def test_telegram_valid_image_uses_send_photo() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"ok": True}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(bot_token="token", chat_id="123", client=client)
            assert await notifier.send("message", image_url=IMAGE_URL) is True

        assert len(requests) == 1
        assert requests[0].url.path.endswith("/sendPhoto")
        assert json.loads(requests[0].content) == {
            "chat_id": "123",
            "photo": IMAGE_URL,
            "caption": "message",
        }

    asyncio.run(run())


def test_telegram_without_image_uses_send_message_only() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"ok": True}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(bot_token="token", chat_id="123", client=client)
            assert await notifier.send("message") is True

        assert len(requests) == 1
        assert requests[0].url.path.endswith("/sendMessage")
        payload = json.loads(requests[0].content)
        assert payload["chat_id"] == "123"
        assert payload["text"] == "message"
        assert "photo" not in payload

    asyncio.run(run())


def test_telegram_invalid_image_is_omitted_from_text_payload() -> None:
    async def run() -> None:
        invalid_image_url = "not-an-http-image-url"
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"ok": True}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(bot_token="token", chat_id="123", client=client)
            assert await notifier.send("message", image_url=invalid_image_url) is True

        assert len(requests) == 1
        assert requests[0].url.path.endswith("/sendMessage")
        assert invalid_image_url not in requests[0].content.decode()

    asyncio.run(run())


@pytest.mark.parametrize("photo_failure", ["http", "invalid_json", "telegram_error"])
def test_telegram_photo_failure_falls_back_to_text(photo_failure: str) -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 1:
                if photo_failure == "http":
                    return httpx.Response(500, json={"ok": False}, request=request)
                if photo_failure == "invalid_json":
                    return httpx.Response(200, content=b"not-json", request=request)
                return httpx.Response(200, json={"ok": False}, request=request)
            return httpx.Response(200, json={"ok": True}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(bot_token="token", chat_id="123", client=client)
            assert await notifier.send("message", image_url=IMAGE_URL) is True

        assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
            "sendPhoto",
            "sendMessage",
        ]
        assert json.loads(requests[1].content)["text"] == "message"

    asyncio.run(run())


def test_telegram_photo_and_text_failures_raise_without_token() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(500, json={"ok": False}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(bot_token="secret-token", chat_id="123", client=client)
            with pytest.raises(TelegramDeliveryError) as exc_info:
                await notifier.send("message", image_url=IMAGE_URL)

        assert len(requests) == 2
        assert requests[0].url.path.endswith("/sendPhoto")
        assert requests[1].url.path.endswith("/sendMessage")
        assert "secret-token" not in str(exc_info.value)

    asyncio.run(run())


def test_telegram_bot_token_is_not_written_to_httpx_logs(caplog) -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True}, request=request)

        caplog.set_level(logging.INFO, logger="httpx")
        httpx_logger = logging.getLogger("httpx")
        level_before = httpx_logger.level
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(bot_token="secret-token", chat_id="123", client=client)
            await notifier.send("message")

        telegram_logs = [
            record.getMessage()
            for record in caplog.records
            if "api.telegram.org" in record.getMessage()
        ]
        assert telegram_logs
        assert all("secret-token" not in message for message in telegram_logs)
        assert all(
            "api.telegram.org/bot<redacted>/sendMessage" in message for message in telegram_logs
        )
        assert httpx_logger.level == level_before

    asyncio.run(run())


def test_telegram_bot_token_is_not_written_to_send_photo_httpx_logs(caplog) -> None:
    async def run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True}, request=request)

        caplog.set_level(logging.INFO, logger="httpx")
        httpx_logger = logging.getLogger("httpx")
        level_before = httpx_logger.level
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            notifier = TelegramNotifier(
                bot_token="photo-secret-token",
                chat_id="123",
                client=client,
            )
            await notifier.send("message", image_url=IMAGE_URL)

        telegram_logs = [
            record.getMessage()
            for record in caplog.records
            if "api.telegram.org" in record.getMessage()
        ]
        assert telegram_logs
        assert all("photo-secret-token" not in message for message in telegram_logs)
        assert all(
            "api.telegram.org/bot<redacted>/sendPhoto" in message for message in telegram_logs
        )
        assert httpx_logger.level == level_before

    asyncio.run(run())


def test_telegram_requires_credentials_outside_dry_run() -> None:
    with pytest.raises(ValueError, match="required"):
        TelegramNotifier()
