from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from time import mktime
from typing import Any, Protocol

import feedparser
import httpx

from gal_radar.adapters.base import SourceAdapterError
from gal_radar.config import FollowConfig, ItchAppConfig
from gal_radar.models.event import SourceEvent
from gal_radar.services.news_classifier import classify_news, extract_release_date, summarize_text

logger = logging.getLogger(__name__)

ITCH_TIMEOUT_SECONDS = 15.0


class _HttpClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> httpx.Response: ...


class ItchAdapter:
    name = "itch.io"
    mode = "feed"

    def __init__(
        self,
        client: _HttpClient | None = None,
        *,
        timeout_seconds: float = ITCH_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)

    async def fetch_events(self, follow: FollowConfig) -> list[SourceEvent]:
        if not follow.itch_apps:
            return []
        
        events: list[SourceEvent] = []
        if self._client is not None:
            for app in follow.itch_apps:
                try:
                    events.extend(await self._fetch_feed(self._client, app))
                except Exception:
                    logger.exception("itch.io app failed url=%s", app.url)
        else:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                for app in follow.itch_apps:
                    try:
                        events.extend(await self._fetch_feed(client, app))
                    except Exception:
                        logger.exception("itch.io app failed url=%s", app.url)
        return events

    async def _fetch_feed(self, client: _HttpClient, app: ItchAppConfig) -> list[SourceEvent]:
        base_url_str = str(app.url).rstrip("/")
        devlog_url = f"{base_url_str}/devlog.rss"
        try:
            response = await client.get(devlog_url, timeout=self._timeout)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise SourceAdapterError(f"itch.io request timed out for {devlog_url}") from exc
        except httpx.HTTPError as exc:
            raise SourceAdapterError(f"itch.io request failed for {devlog_url}") from exc

        parsed = feedparser.parse(response.content)
        if parsed.bozo and parsed.bozo_exception:
            raise SourceAdapterError(f"Malformed feed from {devlog_url}: {parsed.bozo_exception}")

        feed_hash = hashlib.md5(base_url_str.encode("utf-8")).hexdigest()[:8]
        events: list[SourceEvent] = []

        for entry in parsed.entries:
            events.append(self._to_source_event(app, base_url_str, devlog_url, feed_hash, entry))

        return events

    def _to_source_event(
        self,
        app: ItchAppConfig,
        base_url_str: str,
        devlog_url: str,
        feed_hash: str,
        entry: feedparser.FeedParserDict,
    ) -> SourceEvent:
        entry_title = entry.get("title", "Untitled")
        entry_link = entry.get("link", devlog_url)
        entry_summary = entry.get("summary", "") or entry.get("description", "")
        
        entry_id = entry.get("id") or entry.get("guid") or entry_link
        
        tags = []
        for tag in entry.get("tags", []):
            if "term" in tag:
                tags.append(tag["term"])

        published_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if published_time:
            published_at = datetime.fromtimestamp(mktime(published_time), tz=UTC)
        else:
            published_at = datetime.now(UTC)

        event_type = classify_news(entry_title, entry_summary, tags)
        release_date = extract_release_date(f"{entry_title}\n{entry_summary}")
        
        feed_key = f"itch:{base_url_str}"
        metadata: dict[str, Any] = {
            "feed_url": devlog_url,
            "rss_guid": entry_id,
            "news_title": entry_title.strip(),
            "feed_key": feed_key,
        }
        if release_date is not None:
            metadata["release_date"] = release_date

        developer_names = [app.developer] if app.developer else []
        
        return SourceEvent(
            source=self.name,
            source_event_id=f"{feed_hash}:{entry_id}",
            vn_id=app.vn_id,
            developer_names=developer_names,
            tags=tags,
            event_type=event_type,
            title=app.title or entry_title,
            summary=summarize_text(entry_title, entry_summary),
            url=entry_link,
            published_at=published_at,
            metadata=metadata,
        )
