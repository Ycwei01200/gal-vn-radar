from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gal_radar.adapters.base import SourceAdapterError
from gal_radar.config import FollowConfig, SteamAppConfig
from gal_radar.models.event import SourceEvent
from gal_radar.services.news_classifier import classify_news, extract_release_date, summarize_text

logger = logging.getLogger(__name__)

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
            try:
                response = await self._get_news(client, app.app_id)
                events.extend(
                    self._to_source_event(app, item) for item in response.appnews.newsitems
                )
            except Exception:
                logger.exception("Steam app failed app_id=%s", app.app_id)
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
        event_type = classify_news(item.title, item.contents, item.tags)
        release_date = extract_release_date(f"{item.title}\n{item.contents}")
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
            tags=item.tags,
            event_type=event_type,
            title=app.title,
            summary=summarize_text(item.title, item.contents),
            url=item.url or f"https://store.steampowered.com/news/app/{app.app_id}",
            published_at=datetime.fromtimestamp(item.date, tz=UTC),
            metadata=metadata,
        )
