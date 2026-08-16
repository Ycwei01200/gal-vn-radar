from __future__ import annotations

import logging
import re
import sys
from datetime import date
from typing import Any, Literal, Protocol, TextIO
from urllib.parse import urlparse

import httpx

from gal_radar.database import EventRecord
from gal_radar.models.event import EventType


class _HttpClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


_TELEGRAM_BOT_URL_PATTERN = re.compile(r"(https://api\.telegram\.org/bot)[^/\s\"']+")


class _TelegramHttpxLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_telegram_url(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_telegram_url(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _redact_telegram_url(value) for key, value in record.args.items()}
        return True


def _redact_telegram_url(value: Any) -> Any:
    if isinstance(value, str):
        return _TELEGRAM_BOT_URL_PATTERN.sub(r"\1<redacted>", value)
    if isinstance(value, httpx.URL):
        return _TELEGRAM_BOT_URL_PATTERN.sub(r"\1<redacted>", str(value))
    return value


def _ensure_httpx_log_redaction() -> None:
    logger = logging.getLogger("httpx")
    if not any(isinstance(item, _TelegramHttpxLogFilter) for item in logger.filters):
        logger.addFilter(_TelegramHttpxLogFilter())


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
        stdout: TextIO | None = None,
        image_delivery: Literal["photo", "document"] = "photo",
    ) -> None:
        self._bot_token = (bot_token or "").strip()
        self._chat_id = (chat_id or "").strip()
        self._dry_run = dry_run
        self._client = client
        self._stdout = stdout if stdout is not None else sys.stdout
        self._image_delivery = image_delivery
        if not dry_run and (not self._bot_token or not self._chat_id):
            raise ValueError("Telegram bot token and chat ID are required when dry-run is disabled")

    async def send(self, message: str, *, image_url: str | None = None) -> bool:
        if self._dry_run:
            print(message, file=self._stdout)
            return False

        _ensure_httpx_log_redaction()
        if self._client is not None:
            await self._send_with_fallback(self._client, message, image_url)
        else:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await self._send_with_fallback(client, message, image_url)
        return True

    async def _send_with_fallback(
        self,
        client: _HttpClient,
        message: str,
        image_url: str | None,
    ) -> None:
        if _is_valid_image_url(image_url):
            if self._image_delivery == "document":
                try:
                    await self._send_document(client, message, image_url)
                    return
                except TelegramDeliveryError:
                    pass
            try:
                await self._send_photo(client, message, image_url)
                return
            except TelegramDeliveryError:
                pass

        text_url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        text_payload = {
            "chat_id": self._chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        await self._send_with_client(client, text_url, text_payload)

    async def _send_document(
        self,
        client: _HttpClient,
        message: str,
        image_url: str,
    ) -> None:
        document_url = f"https://api.telegram.org/bot{self._bot_token}/sendDocument"
        payload = {
            "chat_id": self._chat_id,
            "document": image_url,
            "caption": message,
        }
        await self._send_with_client(client, document_url, payload)

    async def _send_photo(
        self,
        client: _HttpClient,
        message: str,
        image_url: str,
    ) -> None:
        photo_url = f"https://api.telegram.org/bot{self._bot_token}/sendPhoto"
        payload = {
            "chat_id": self._chat_id,
            "photo": image_url,
            "caption": message,
        }
        await self._send_with_client(client, photo_url, payload)

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


def _is_valid_image_url(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def render_zh_tw_notification(
    event: EventRecord,
    *,
    source_priority: list[str] | None = None,
) -> str:
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

    source_names = "、".join(
        _source_display(source) for source in _ordered_sources(event, source_priority)
    )
    lines.extend(["", f"來源：{source_names}", "🔗 查看來源", event.url])
    return "\n".join(lines)


def render_zh_tw_digest(
    events: list[EventRecord],
    *,
    source_priority: list[str] | None = None,
) -> str:
    if not events:
        return ""
    lines = ["📚 今日 Gal/VN Radar 摘要\n"]
    for i, event in enumerate(events, start=1):
        event_type = EventType(event.event_type)
        source_names = "、".join(
            _source_display(source) for source in _ordered_sources(event, source_priority)
        )
        lines.append(f"{i}. 《{event.title}》 (來源：{source_names})")
        lines.append(_heading(event_type))

        release_date = event.metadata_json.get("release_date")
        if isinstance(release_date, str) and release_date:
            lines.append(f"{_release_label(event_type)}{_format_release_date(release_date)}")
        elif event.summary:
            lines.append(event.summary)
        else:
            lines.append("無詳細內容")
        lines.append("")
    lines.append(f"共 {len(events)} 則你可能感興趣的情報。")
    return "\n".join(lines)


def _ordered_sources(
    event: EventRecord,
    source_priority: list[str] | None = None,
) -> list[str]:
    sources = [event.source]
    for corroboration in getattr(event, "corroborating_sources", None) or []:
        source = corroboration.get("source")
        if isinstance(source, str) and source not in sources:
            sources.append(source)

    if not source_priority:
        return sources
    priority = {source: index for index, source in enumerate(source_priority)}
    return sorted(
        sources,
        key=lambda source: (priority.get(source, len(priority)), sources.index(source)),
    )


def _source_display(source: str) -> str:
    return {
        "vndb": "VNDB",
        "steam": "Steam",
        "rss": "官方 RSS",
        "itch.io": "itch.io",
    }.get(source, source)


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
    if reason == "discovered visual novel":
        return "這是 Radar 自動發現的近期 VN"
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
