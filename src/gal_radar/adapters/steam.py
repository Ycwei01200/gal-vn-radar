from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gal_radar.adapters.base import SourceAdapterError
from gal_radar.config import FollowConfig, SteamAppConfig
from gal_radar.models.event import EventType, SourceEvent

STEAM_NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
STEAM_TIMEOUT_SECONDS = 15.0
DEFAULT_NEWS_COUNT = 20
DEFAULT_MAX_LENGTH = 1200


class _HttpClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> httpx.Response: ...


class _SteamNewsItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gid: str
    title: str
    url: str
    author: str | None = None
    contents: str = ""
    date: int
    tags: list[str] = Field(default_factory=list)


class _SteamAppNews(BaseModel):
    model_config = ConfigDict(extra="ignore")

    appid: int
    newsitems: list[_SteamNewsItem] = Field(default_factory=list)


class _SteamNewsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    appnews: _SteamAppNews


class SteamNewsAdapter:
    name = "steam"
    mode = "feed"

    def __init__(
        self,
        client: _HttpClient | None = None,
        *,
        timeout_seconds: float = STEAM_TIMEOUT_SECONDS,
        count: int = DEFAULT_NEWS_COUNT,
        max_length: int = DEFAULT_MAX_LENGTH,
    ) -> None:
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._count = count
        self._max_length = max_length

    async def fetch_events(self, follow: FollowConfig) -> list[SourceEvent]:
        if not follow.steam_apps:
            return []
        if self._client is not None:
            return await self._fetch_with_client(self._client, follow)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._fetch_with_client(client, follow)

    async def _fetch_with_client(
        self,
        client: _HttpClient,
        follow: FollowConfig,
    ) -> list[SourceEvent]:
        events: list[SourceEvent] = []
        for app in follow.steam_apps:
            response = await self._get_news(client, app.app_id)
            events.extend(self._to_source_event(app, item) for item in response.appnews.newsitems)
        return events

    async def _get_news(self, client: _HttpClient, app_id: int) -> _SteamNewsResponse:
        try:
            response = await client.get(
                STEAM_NEWS_URL,
                params={
                    "appid": app_id,
                    "count": self._count,
                    "maxlength": self._max_length,
                    "format": "json",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise SourceAdapterError(f"Steam News request timed out app_id={app_id}") from exc
        except httpx.HTTPError as exc:
            raise SourceAdapterError(f"Steam News request failed app_id={app_id}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise SourceAdapterError("Steam News returned invalid JSON") from exc
        try:
            parsed = _SteamNewsResponse.model_validate(body)
        except ValidationError as exc:
            raise SourceAdapterError("Malformed Steam News response") from exc
        if parsed.appnews.appid != app_id:
            raise SourceAdapterError(
                f"Steam News returned unexpected app_id={parsed.appnews.appid}; expected {app_id}"
            )
        return parsed

    def _to_source_event(self, app: SteamAppConfig, item: _SteamNewsItem) -> SourceEvent:
        event_type = _classify_news(item.title, item.contents, item.tags)
        release_date = _extract_release_date(f"{item.title}\n{item.contents}")
        metadata: dict[str, Any] = {
            "steam_app_id": app.app_id,
            "steam_gid": item.gid,
            "news_title": item.title.strip(),
            "feed_key": f"steam:{app.app_id}",
        }
        if release_date is not None:
            metadata["release_date"] = release_date

        developer_names = [app.developer] if app.developer else []
        return SourceEvent(
            source=self.name,
            source_event_id=f"{app.app_id}:{item.gid}",
            vn_id=app.vn_id,
            developer_names=developer_names,
            event_type=event_type,
            title=app.title,
            summary=_summarize(item.title, item.contents),
            url=item.url,
            published_at=datetime.fromtimestamp(item.date, tz=UTC),
            metadata=metadata,
        )


def _classify_news(title: str, contents: str, tags: list[str]) -> EventType:
    haystack = " ".join([title, contents, *tags]).casefold()
    if _contains_any(haystack, ("延期", "delay", "delayed", "postpone", "postponed")):
        return EventType.DELAY
    if _contains_any(
        haystack,
        ("release date", "launch date", "発売日", "發售日", "发售日"),
    ):
        return EventType.RELEASE_DATE
    if _contains_any(
        haystack,
        ("demo", "体験版", "體驗版", "试玩版", "trial version"),
    ):
        return EventType.DEMO
    if _contains_any(
        haystack,
        ("patch", "hotfix", "update", "更新", "アップデート", "version ", "ver."),
    ):
        return EventType.PATCH
    if _contains_any(haystack, ("trailer", "movie", "pv", "プロモーションムービー")):
        return EventType.TRAILER
    if _contains_any(
        haystack,
        (
            "now available",
            "available now",
            "released today",
            "now on sale",
            "発売開始",
            "正式發售",
            "正式发售",
        ),
    ):
        return EventType.RELEASED
    if _contains_any(haystack, ("devlog", "developer update", "開発日誌", "開發日誌")):
        return EventType.DEVLOG
    return EventType.OTHER


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle.casefold() in value for needle in needles)


def _extract_release_date(value: str) -> str | None:
    iso_match = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", value)
    if iso_match:
        return _validated_date(*iso_match.groups())

    month_names = {
        name.casefold(): number
        for number, name in enumerate(
            (
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ),
            start=1,
        )
    }
    month_pattern = "|".join(month_names)
    mdy_match = re.search(
        rf"\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b",
        value,
        flags=re.IGNORECASE,
    )
    if mdy_match:
        month, day, year = mdy_match.groups()
        return _validated_date(year, str(month_names[month.casefold()]), day)

    dmy_match = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})\s+(20\d{{2}})\b",
        value,
        flags=re.IGNORECASE,
    )
    if dmy_match:
        day, month, year = dmy_match.groups()
        return _validated_date(year, str(month_names[month.casefold()]), day)
    return None


def _validated_date(year: str, month: str, day: str) -> str | None:
    try:
        parsed = datetime(int(year), int(month), int(day), tzinfo=UTC)
    except ValueError:
        return None
    return parsed.date().isoformat()


def _summarize(title: str, contents: str) -> str:
    cleaned = _plain_text(contents)
    if cleaned:
        return f"{title.strip()} — {cleaned}"[:500].rstrip()
    return title.strip()[:500]


def _plain_text(value: str) -> str:
    without_bbcode = re.sub(r"\[/?[^\]]+\]", " ", value)
    without_html = re.sub(r"<[^>]+>", " ", without_bbcode)
    return re.sub(r"\s+", " ", html.unescape(without_html)).strip()
