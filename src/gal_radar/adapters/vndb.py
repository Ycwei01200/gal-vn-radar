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
from gal_radar.config import FeedConfig, FollowConfig, ItchAppConfig, SteamAppConfig
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


class _VNDBReleaseVN(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str


class _VNDBRelease(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    vns: list[_VNDBReleaseVN] = Field(default_factory=list)
    extlinks: list[_VNDBExtLink] = Field(default_factory=list)


class _VNDBReleaseQueryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_VNDBRelease]
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
        discover_itch: bool = True,
        discover_feeds: bool = True,
    ) -> None:
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_retries = max_retries
        self._sleep = sleep
        self._now = now
        self._discovery_enabled = discovery_enabled
        self._discovery_results = min(max(discovery_results, 1), _MAX_RESULTS_PER_QUERY)
        self._discover_steam = discover_steam
        self._discover_itch = discover_itch
        self._discover_feeds = discover_feeds

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
            logger.info("VNDB auto-discovered %d release-sorted titles", len(response.results))

        follow.set_resolved_developer_ids(resolved_developer_ids)

        release_steam_apps: dict[str, set[int]] = {}
        if self._discover_steam:
            missing_direct_steam = [vn for vn in vns if not _steam_app_ids(vn.extlinks)]
            if missing_direct_steam:
                try:
                    release_steam_apps = await self._discover_release_steam_apps(
                        client,
                        missing_direct_steam,
                    )
                except Exception:
                    logger.exception(
                        "VNDB release Steam discovery failed; continuing with VN extlinks"
                    )

        self._discover_external_sources(follow, vns, release_steam_apps)
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

    async def _discover_release_steam_apps(
        self,
        client: _HttpClient,
        vns: list[_VNDBVN],
    ) -> dict[str, set[int]]:
        vn_ids = {vn.id for vn in vns}
        if not vn_ids:
            return {}

        id_filters: list[list[Any]] = [["id", "=", vn_id] for vn_id in sorted(vn_ids)]
        vn_filter: list[Any]
        if len(id_filters) == 1:
            vn_filter = id_filters[0]
        else:
            vn_filter = ["or", *id_filters]

        filters: list[Any] = [
            "and",
            ["extlink", "=", "steam"],
            ["vn", "=", vn_filter],
        ]
        mappings: dict[str, set[int]] = {}
        page = 1

        while True:
            data = await self._post_json(
                client,
                "/release",
                {
                    "filters": filters,
                    "fields": "vns{id},extlinks{name,id,url}",
                    "sort": "id",
                    "results": _MAX_RESULTS_PER_QUERY,
                    "page": page,
                },
            )
            try:
                response = _VNDBReleaseQueryResponse.model_validate(data)
            except ValidationError as exc:
                raise SourceAdapterError("Malformed VNDB /release response") from exc

            for release in response.results:
                app_ids = _steam_app_ids(release.extlinks)
                if not app_ids:
                    continue
                for linked_vn in release.vns:
                    if linked_vn.id not in vn_ids:
                        continue
                    mappings.setdefault(linked_vn.id, set()).update(app_ids)

            if not response.more:
                break
            page += 1

        logger.info(
            "VNDB release Steam discovery matched vns=%d apps=%d",
            len(mappings),
            len({app_id for app_ids in mappings.values() for app_id in app_ids}),
        )
        return mappings

    def _discover_external_sources(
        self,
        follow: FollowConfig,
        vns: list[_VNDBVN],
        release_steam_apps: dict[str, set[int]] | None = None,
    ) -> None:
        steam_count = 0
        itch_count = 0
        feed_count = 0
        release_steam_apps = release_steam_apps or {}

        for vn in vns:
            developer = vn.developers[0].name if vn.developers else None
            title = vn.alttitle or vn.title

            if self._discover_steam:
                app_ids = set(_steam_app_ids(vn.extlinks))
                app_ids.update(release_steam_apps.get(vn.id, set()))
                for app_id in sorted(app_ids):
                    before = len(follow.steam_apps)
                    follow.add_discovered_steam_app(
                        SteamAppConfig(
                            app_id=app_id,
                            vn_id=vn.id,
                            title=title,
                            developer=developer,
                        )
                    )
                    steam_count += int(len(follow.steam_apps) > before)

            if self._discover_itch:
                itch_url = _itch_game_url(vn.extlinks)
                if itch_url is not None:
                    before = len(follow.itch_apps)
                    follow.add_discovered_itch_app(
                        ItchAppConfig(
                            url=itch_url,
                            vn_id=vn.id,
                            title=title,
                            developer=developer,
                        )
                    )
                    itch_count += int(len(follow.itch_apps) > before)

            if self._discover_feeds:
                for feed_url in _feed_urls(vn.extlinks):
                    before = len(follow.feeds)
                    follow.add_discovered_feed(
                        FeedConfig(
                            url=feed_url,
                            vn_id=vn.id,
                            title=title,
                            developer=developer,
                        )
                    )
                    feed_count += int(len(follow.feeds) > before)

        logger.info(
            "auto-discovered external mappings steam=%d itch=%d feeds=%d",
            steam_count,
            itch_count,
            feed_count,
        )

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


def _steam_app_ids(extlinks: list[_VNDBExtLink]) -> list[int]:
    app_ids: list[int] = []
    for link in extlinks:
        name_is_steam = (link.name or "").casefold() == "steam"
        match = re.search(r"store\.steampowered\.com/app/(\d+)", link.url, flags=re.IGNORECASE)
        if not name_is_steam and match is None:
            continue

        app_id: int | None = None
        if isinstance(link.id, int) and link.id > 0:
            app_id = link.id
        elif isinstance(link.id, str) and link.id.isdigit() and int(link.id) > 0:
            app_id = int(link.id)
        elif match:
            app_id = int(match.group(1))

        if app_id is not None and app_id not in app_ids:
            app_ids.append(app_id)
    return app_ids


def _steam_app_id(extlinks: list[_VNDBExtLink]) -> int | None:
    app_ids = _steam_app_ids(extlinks)
    return app_ids[0] if app_ids else None


def _itch_game_url(extlinks: list[_VNDBExtLink]) -> str | None:
    for link in extlinks:
        if re.match(r"https?://[^/]+\.itch\.io/[^/?#]+/?$", link.url, flags=re.IGNORECASE):
            return link.url.rstrip("/")
    return None


def _feed_urls(extlinks: list[_VNDBExtLink]) -> list[str]:
    urls: list[str] = []
    for link in extlinks:
        lowered = link.url.casefold()
        looks_like_feed = (
            lowered.endswith((".rss", ".atom", ".xml"))
            or "/feed" in lowered
            or "rss" in lowered
        )
        if looks_like_feed and link.url not in urls:
            urls.append(link.url)
    return urls


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
