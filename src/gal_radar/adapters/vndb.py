from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any, Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from gal_radar.adapters.base import SourceAdapterError
from gal_radar.config import FollowConfig, SteamAppConfig
from gal_radar.models.event import EventType, SourceEvent

logger = logging.getLogger(__name__)

VNDB_BASE_URL = "https://api.vndb.org/kana"
VNDB_TIMEOUT_SECONDS = 15.0
_MAX_RESULTS_PER_QUERY = 100


class _HttpClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class _VNDBDeveloper(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str


class _VNDBTag(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str


class _VNDBImage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: HttpUrl | None = None


class _VNDBExtLink(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    id: str | int | None = None
    url: str


class _VNDBVN(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    alttitle: str | None = None
    released: str | None = None
    developers: list[_VNDBDeveloper] = Field(default_factory=list)
    image: _VNDBImage | None = None
    tags: list[_VNDBTag] = Field(default_factory=list)
    extlinks: list[_VNDBExtLink] = Field(default_factory=list)


class _VNDBQueryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_VNDBVN]
    more: bool = False


class _VNDBProducer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str


class _VNDBProducerResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_VNDBProducer]


class VNDBAdapter:
    name = "vndb"

    def __init__(
        self,
        client: _HttpClient | None = None,
        *,
        timeout_seconds: float = VNDB_TIMEOUT_SECONDS,
        max_retries: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        discovery_enabled: bool = False,
        discovery_results: int = 50,
        discover_steam: bool = True,
    ) -> None:
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_retries = max_retries
        self._sleep = sleep
        self._now = now
        self._discovery_enabled = discovery_enabled
        self._discovery_results = min(max(discovery_results, 1), _MAX_RESULTS_PER_QUERY)
        self._discover_steam = discover_steam

    async def fetch_events(self, follow: FollowConfig) -> list[SourceEvent]:
        if self._client is not None:
            return await self._fetch_with_client(self._client, follow)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._fetch_with_client(client, follow)

    async def _fetch_with_client(
        self,
        client: _HttpClient,
        follow: FollowConfig,
    ) -> list[SourceEvent]:
        seen_vn_ids: set[str] = set()
        resolved_developer_ids: list[str] = []
        vns: list[_VNDBVN] = []

        for item in follow.visual_novels:
            response = await self._query_vn(client, self._visual_novel_filter(item))
            self._collect_vns(response.results, seen_vn_ids, vns)

        for developer_name in follow.developers:
            producer = await self._resolve_producer(client, developer_name)
            if producer is None:
                logger.warning("VNDB producer not found name=%r", developer_name)
                continue
            if producer.id not in resolved_developer_ids:
                resolved_developer_ids.append(producer.id)
            response = await self._query_vn(
                client,
                ["developer", "=", ["id", "=", producer.id]],
                sort="released",
                reverse=True,
            )
            self._collect_vns(response.results, seen_vn_ids, vns)

        if self._discovery_enabled:
            response = await self._query_vn(
                client,
                [],
                sort="released",
                reverse=True,
                results=self._discovery_results,
            )
            for vn in response.results:
                follow.add_discovered_vn(vn.id)
            self._collect_vns(response.results, seen_vn_ids, vns)
            logger.info("VNDB auto-discovered %d recent titles", len(response.results))

        follow.set_resolved_developer_ids(resolved_developer_ids)
        if self._discover_steam:
            self._discover_steam_apps(follow, vns)
        return [self._to_source_event(vn) for vn in vns]

    @staticmethod
    def _collect_vns(
        candidates: list[_VNDBVN],
        seen_vn_ids: set[str],
        output: list[_VNDBVN],
    ) -> None:
        for vn in candidates:
            if vn.id not in seen_vn_ids:
                seen_vn_ids.add(vn.id)
                output.append(vn)

    def _discover_steam_apps(self, follow: FollowConfig, vns: list[_VNDBVN]) -> None:
        discovered = 0
        for vn in vns:
            app_id = _steam_app_id(vn.extlinks)
            if app_id is None:
                continue
            before = len(follow.steam_apps)
            developer = vn.developers[0].name if vn.developers else None
            follow.add_discovered_steam_app(
                SteamAppConfig(
                    app_id=app_id,
                    vn_id=vn.id,
                    title=vn.alttitle or vn.title,
                    developer=developer,
                )
            )
            if len(follow.steam_apps) > before:
                discovered += 1
        if discovered:
            logger.info("auto-discovered %d Steam app mappings from VNDB extlinks", discovered)

    async def _query_vn(
        self,
        client: _HttpClient,
        filters: list[Any],
        *,
        sort: str = "id",
        reverse: bool = False,
        results: int = 20,
    ) -> _VNDBQueryResponse:
        payload = {
            "filters": filters,
            "fields": (
                "title,alttitle,released,developers{id,name},image{url},"
                "tags{id,name},extlinks{name,id,url}"
            ),
            "sort": sort,
            "reverse": reverse,
            "results": min(max(results, 1), _MAX_RESULTS_PER_QUERY),
        }
        data = await self._post_json(client, "/vn", payload)
        try:
            return _VNDBQueryResponse.model_validate(data)
        except ValidationError as exc:
            raise SourceAdapterError("Malformed VNDB /vn response") from exc

    async def _resolve_producer(
        self,
        client: _HttpClient,
        name: str,
    ) -> _VNDBProducer | None:
        data = await self._post_json(
            client,
            "/producer",
            {
                "filters": ["search", "=", name],
                "fields": "name",
                "results": 1,
            },
        )
        try:
            response = _VNDBProducerResponse.model_validate(data)
        except ValidationError as exc:
            raise SourceAdapterError("Malformed VNDB /producer response") from exc
        return response.results[0] if response.results else None

    async def _post_json(
        self,
        client: _HttpClient,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"{VNDB_BASE_URL}{path}"
        for attempt in range(self._max_retries + 1):
            try:
                response = await client.post(url, json=payload, timeout=self._timeout)
            except httpx.TimeoutException as exc:
                raise SourceAdapterError(f"VNDB request timed out path={path}") from exc
            except httpx.HTTPError as exc:
                raise SourceAdapterError(f"VNDB request failed path={path}") from exc

            if response.status_code == 429 and attempt < self._max_retries:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                await self._sleep(retry_after)
                continue

            if response.status_code == 429:
                raise SourceAdapterError("VNDB rate limit exceeded")

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise SourceAdapterError(
                    f"VNDB returned HTTP {response.status_code} path={path}"
                ) from exc

            try:
                body = response.json()
            except ValueError as exc:
                raise SourceAdapterError("VNDB returned invalid JSON") from exc
            if not isinstance(body, dict):
                raise SourceAdapterError("VNDB returned a non-object JSON response")
            return cast(dict[str, Any], body)

        raise SourceAdapterError("VNDB request failed after retries")

    def _to_source_event(self, vn: _VNDBVN) -> SourceEvent:
        event_type = _event_type_for_release(vn.released, self._now().date())
        release_token = vn.released or "unknown"
        source_event_id = f"{vn.id}:{event_type.value}:{release_token}"
        developer_ids = [developer.id for developer in vn.developers]
        developer_names = [developer.name for developer in vn.developers]
        developer_id = developer_ids[0] if developer_ids else None
        title = vn.alttitle or vn.title
        summary = _summary_for_release(vn.released)
        metadata: dict[str, Any] = {}
        if vn.released:
            metadata["release_date"] = vn.released
        steam_app_id = _steam_app_id(vn.extlinks)
        if steam_app_id is not None:
            metadata["steam_app_id"] = steam_app_id
        return SourceEvent(
            source=self.name,
            source_event_id=source_event_id,
            vn_id=vn.id,
            developer_id=developer_id,
            developer_ids=developer_ids,
            developer_names=developer_names,
            tags=[tag.name for tag in vn.tags],
            event_type=event_type,
            title=title,
            summary=summary,
            url=f"https://vndb.org/{vn.id}",
            image_url=vn.image.url if vn.image else None,
            metadata=metadata,
        )

    @staticmethod
    def _visual_novel_filter(value: str) -> list[Any]:
        stripped = value.strip()
        if re.fullmatch(r"v\d+", stripped, flags=re.IGNORECASE):
            return ["id", "=", stripped.lower()]
        return ["search", "=", stripped]


def _steam_app_id(extlinks: list[_VNDBExtLink]) -> int | None:
    for link in extlinks:
        if (link.name or "").casefold() != "steam":
            continue
        if isinstance(link.id, int) and link.id > 0:
            return link.id
        if isinstance(link.id, str) and link.id.isdigit() and int(link.id) > 0:
            return int(link.id)
        match = re.search(r"store\.steampowered\.com/app/(\d+)", link.url, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _event_type_for_release(value: str | None, today: date) -> EventType:
    parsed = _parse_complete_date(value)
    if parsed is None:
        return EventType.NEW_TITLE
    return EventType.RELEASED if parsed <= today else EventType.RELEASE_DATE


def _summary_for_release(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "TBA":
        return "Release date: TBA"
    return f"Release date: {value}"


def _parse_complete_date(value: str | None) -> date | None:
    if value is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    return date.fromisoformat(value)


def _parse_retry_after(value: str | None) -> float:
    if value is None:
        return 1.0
    try:
        return max(float(value), 0.0)
    except ValueError:
        return 1.0
