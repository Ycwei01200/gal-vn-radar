from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from gal_radar.models.event import EventType, NormalizedEvent, SourceEvent

_SINGLETON_EVENT_TYPES = {
    EventType.NEW_TITLE,
    EventType.RELEASED,
    EventType.STEAM_PAGE,
}
_DATE_EVENT_TYPES = {
    EventType.RELEASE_DATE,
    EventType.DELAY,
}


def normalize_event(
    source_event: SourceEvent,
    *,
    discovered_at: datetime | None = None,
) -> NormalizedEvent:
    discovered = discovered_at or datetime.now(UTC)
    normalized_identity = _normalized_identity(source_event)
    content_hash = _content_hash(source_event)
    return NormalizedEvent(
        source=source_event.source,
        source_event_id=source_event.source_event_id,
        vn_id=source_event.vn_id,
        developer_id=source_event.developer_id,
        developer_ids=source_event.developer_ids,
        developer_names=source_event.developer_names,
        tags=source_event.tags,
        event_type=source_event.event_type,
        title=source_event.title.strip(),
        summary=source_event.summary.strip() if source_event.summary else None,
        url=str(source_event.url),
        image_url=str(source_event.image_url) if source_event.image_url else None,
        published_at=source_event.published_at,
        discovered_at=discovered,
        metadata=source_event.metadata,
        normalized_identity=normalized_identity,
        content_hash=content_hash,
    )


def _normalized_identity(event: SourceEvent) -> str:
    entity = event.vn_id or _normalize_text(event.title)
    parts = [entity, event.event_type.value]
    if event.event_type in _DATE_EVENT_TYPES:
        parts.append(str(event.metadata.get("release_date") or ""))
    elif event.event_type not in _SINGLETON_EVENT_TYPES:
        semantic_title = str(event.metadata.get("news_title") or event.title)
        parts.append(_normalize_text(semantic_title))
    return "|".join(parts)


def _content_hash(event: SourceEvent) -> str:
    payload: dict[str, Any] = {
        "vn_id": event.vn_id,
        "event_type": event.event_type.value,
        "title": _normalize_text(event.title),
        "summary": _normalize_text(event.summary or ""),
        "metadata": event.metadata,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()
