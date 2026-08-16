from __future__ import annotations

import logging
import sys
from datetime import date
from typing import Any, Protocol, TextIO

import httpx

from gal_radar.database import EventRecord
from gal_radar.models.event import EventType


class _HttpClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class TelegramDeliveryError(RuntimeError):
    pass


class TelegramNotifier:
    def __init__(
        self,
        *,
        bot_token: str | None = None,
        chat_id: str | None = None,
        dry_run: bool = False,
        client: _HttpClient | None = None,
        stdout: TextIO = sys.stdout,
    ) -> None:
        self._bot_token = (bot_token or "").strip()
        self._chat_id = (chat_id or "").strip()
        self._dry_run = dry_run
        self._client = client
        self._stdout = stdout
        if not dry_run and (not self._bot_token or not self._chat_id):
            raise ValueError("Telegram bot token and chat ID are required when dry-run is disabled")

    async def send(self, message: str) -> bool:
        if self._dry_run:
            print(message, file=self._stdout)
            return False

        # HTTPX includes the full request URL in INFO logs; this URL contains
        # the Telegram bot token, so request logging must not expose it.
        httpx_logger = logging.getLogger("httpx")
        httpx_logger.setLevel(max(httpx_logger.level, logging.WARNING))
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        if self._client is not None:
            await self._send_with_client(self._client, url, payload)
        else:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await self._send_with_client(client, url, payload)
        return True

    @staticmethod
    async def _send_with_client(
        client: _HttpClient,
        url: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            response = await client.post(url, json=payload, timeout=15.0)
            response.raise_for_status()
        except httpx.HTTPError:
            raise TelegramDeliveryError("Telegram delivery request failed") from None

        try:
            body = response.json()
        except ValueError:
            raise TelegramDeliveryError("Telegram returned invalid JSON") from None
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise TelegramDeliveryError("Telegram did not confirm message delivery")


def render_zh_tw_notification(event: EventRecord) -> str:
    event_type = EventType(event.event_type)
    lines = [_heading(event_type), "", f"《{event.title}》"]
    if event.developer_names:
        lines.append(f"開發商：{'、'.join(event.developer_names)}")

    release_date = event.metadata_json.get("release_date")
    if isinstance(release_date, str) and release_date:
        lines.extend(["", _release_label(event_type), _format_release_date(release_date)])
    elif event.summary:
        lines.extend(["", event.summary])

    lines.extend(["", f"🔥 關聯度：{event.relevance_score}"])
    if event.relevance_reasons:
        lines.extend(["", "你可能會感興趣，因為："])
        lines.extend(f"・{_translate_reason(reason)}" for reason in event.relevance_reasons)

    lines.extend(["", "🔗 查看來源", event.url])
    return "\n".join(lines)


def _heading(event_type: EventType) -> str:
    return {
        EventType.NEW_TITLE: "🆕 新作情報",
        EventType.RELEASE_DATE: "📅 發售日更新",
        EventType.RELEASED: "🎉 正式發售",
        EventType.DELAY: "⏰ 發售延期",
        EventType.DEMO: "🎮 體驗版情報",
        EventType.PATCH: "🛠️ 更新情報",
        EventType.LOCALIZATION: "🌐 在地化情報",
        EventType.STEAM_PAGE: "🛒 Steam 頁面公開",
        EventType.DEVLOG: "📝 開發情報",
        EventType.TRAILER: "🎬 宣傳影片",
        EventType.OTHER: "ℹ️ 相關情報",
    }[event_type]


def _release_label(event_type: EventType) -> str:
    if event_type is EventType.RELEASED:
        return "發售日："
    if event_type is EventType.DELAY:
        return "更新後發售日："
    return "📅 發售日更新"


def _format_release_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{parsed.year} 年 {parsed.month} 月 {parsed.day} 日"


def _translate_reason(reason: str) -> str:
    if reason == "followed visual novel":
        return "你正在追蹤這部作品"
    if reason.startswith("followed developer: "):
        return f"你正在追蹤「{reason.removeprefix('followed developer: ')}」"
    if reason.startswith("matched tag: "):
        return f"符合你偏好的「{reason.removeprefix('matched tag: ')}」標籤"
    if reason == "event type: RELEASE_DATE":
        return "這是一則發售日異動"
    if reason == "event type: RELEASED":
        return "這部作品已正式發售"
    if reason == "event type: NEW_TITLE":
        return "這是一則新作情報"
    if reason == "event type: DEMO":
        return "這是一則體驗版情報"
    if reason == "event type: DELAY":
        return "這是一則發售延期情報"
    return reason
