from __future__ import annotations

import asyncio
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


def _record(event_store):
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
        delivered = await notifier.send(render_zh_tw_notification(_record(event_store)))

        assert delivered is False
        assert "發售日更新" in output.getvalue()

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


def test_telegram_requires_credentials_outside_dry_run() -> None:
    with pytest.raises(ValueError, match="required"):
        TelegramNotifier()
