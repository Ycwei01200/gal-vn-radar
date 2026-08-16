from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from gal_radar.models.event import NormalizedEvent, SourceEvent


def normalize_event(
    source_event: SourceEvent,
    *,
    discovered_at: datetime | None = None,
) -> NormalizedEvent:
    discovered = discovered_at or datetime.now(UTC)
    identity_parts = [
        source_event.vn_id or "no-vn",
        source_event.event_type.value,
        _normalize_text(source_event.title),
        str(source_event.metadata.get("release_date") or ""),
    ]
    normalized_identity = "|".join(identity_parts)
    content_hash = _content_hash(source_event)
    return NormalizedEvent(
        source=source_event.source,
        source_event_id=source_event.source_event_id,
        vn_id=source_event.vn_id,
        developer_id=source_event.developer_id,
        developer_names=source_event.developer_names,
        tags=source_event.tags,
        event_type=source_event.event_type,
        title=source_event.title.strip(),
        summary=source_event.summary.strip() if source_event.summary else None,
        url=str(source_event.url),
        published_at=source_event.published_at,
        discovered_at=discovered,
        metadata=source_event.metadata,
        normalized_identity=normalized_identity,
        content_hash=content_hash,
    )


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
