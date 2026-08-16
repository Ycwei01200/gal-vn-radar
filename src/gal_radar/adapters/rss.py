from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from time import mktime
from typing import Any, Protocol

import feedparser
import httpx

from gal_radar.adapters.base import SourceAdapterError
from gal_radar.config import FeedConfig, FollowConfig
from gal_radar.models.event import SourceEvent
from gal_radar.services.http_safety import (
    ResponseTooLargeError,
    UnsafeUrlError,
    fetch_limited_bytes,
    safe_url_for_log,
)
from gal_radar.services.news_classifier import classify_news, extract_release_date, summarize_text

logger = logging.getLogger(__name__)

RSS_TIMEOUT_SECONDS = 15.0
RSS_MAX_BYTES = 5 * 1024 * 1024


class _HttpClient(Protocol):
    def stream(self, method: str, url: str, **kwargs: Any) -> Any: ...

    async def get(self, url: str, **kwargs: Any) -> httpx.Response: ...


class RSSAdapter:
    name = "rss"
    mode = "feed"

    def __init__(
        self,
        client: _HttpClient | None = None,
        *,
        timeout_seconds: float = RSS_TIMEOUT_SECONDS,
        max_bytes: int = RSS_MAX_BYTES,
    ) -> None:
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_bytes = max_bytes

    async def fetch_events(self, follow: FollowConfig) -> list[SourceEvent]:
        if not follow.feeds:
            return []

        events: list[SourceEvent] = []
        if self._client is not None:
            for feed in follow.feeds:
                try:
                    events.extend(await self._fetch_feed(self._client, feed))
                except Exception:
                    logger.exception("RSS feed failed url=%s", safe_url_for_log(str(feed.url)))
        else:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
                for feed in follow.feeds:
                    try:
                        events.extend(await self._fetch_feed(client, feed))
                    except Exception:
                        logger.exception("RSS feed failed url=%s", safe_url_for_log(str(feed.url)))
        return events

    async def _fetch_feed(self, client: _HttpClient, feed: FeedConfig) -> list[SourceEvent]:
        url_str = str(feed.url)
        try:
            content, final_url, _ = await fetch_limited_bytes(
                client,
                url_str,
                timeout=self._timeout,
                max_bytes=self._max_bytes,
            )
        except (httpx.HTTPError, UnsafeUrlError, ResponseTooLargeError) as exc:
            raise SourceAdapterError(
                f"RSS request rejected for {safe_url_for_log(url_str)}: {exc}"
            ) from exc

        parsed = feedparser.parse(content)
        if parsed.bozo and parsed.bozo_exception:
            raise SourceAdapterError(
                f"Malformed feed from {safe_url_for_log(final_url)}: {parsed.bozo_exception}"
            )

        feed_hash = hashlib.md5(url_str.encode("utf-8")).hexdigest()[:8]
        events: list[SourceEvent] = []
        for entry in parsed.entries:
            events.append(self._to_source_event(feed, url_str, feed_hash, entry))
        return events

    def _to_source_event(
        self,
        feed: FeedConfig,
        url_str: str,
        feed_hash: str,
        entry: feedparser.FeedParserDict,
    ) -> SourceEvent:
        entry_title = entry.get("title", "Untitled")
        entry_link = entry.get("link", url_str)
        entry_summary = entry.get("summary", "") or entry.get("description", "")
        entry_id = entry.get("id") or entry.get("guid") or entry_link

        tags = [tag["term"] for tag in entry.get("tags", []) if "term" in tag]
        published_time = entry.get("published_parsed") or entry.get("updated_parsed")
        published_at = (
            datetime.fromtimestamp(mktime(published_time), tz=UTC)
            if published_time
            else datetime.now(UTC)
        )

        event_type = classify_news(entry_title, entry_summary, tags)
        release_date = extract_release_date(f"{entry_title}\n{entry_summary}")
        feed_key = f"rss:{url_str}"
        metadata: dict[str, Any] = {
            "feed_url": url_str,
            "rss_guid": entry_id,
            "news_title": entry_title.strip(),
            "feed_key": feed_key,
        }
        if release_date is not None:
            metadata["release_date"] = release_date

        developer_names = [feed.developer] if feed.developer else []
        return SourceEvent(
            source=self.name,
            source_event_id=f"{feed_hash}:{entry_id}",
            vn_id=feed.vn_id,
            developer_names=developer_names,
            tags=tags,
            event_type=event_type,
            title=feed.title or entry_title,
            summary=summarize_text(entry_title, entry_summary),
            url=entry_link,
            published_at=published_at,
            metadata=metadata,
        )
