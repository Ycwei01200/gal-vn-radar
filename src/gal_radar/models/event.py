from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class EventType(StrEnum):
    NEW_TITLE = "NEW_TITLE"
    RELEASE_DATE = "RELEASE_DATE"
    RELEASED = "RELEASED"
    DELAY = "DELAY"
    DEMO = "DEMO"
    PATCH = "PATCH"
    LOCALIZATION = "LOCALIZATION"
    STEAM_PAGE = "STEAM_PAGE"
    DEVLOG = "DEVLOG"
    TRAILER = "TRAILER"
    OTHER = "OTHER"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    DIGEST = "DIGEST"
    SKIPPED = "SKIPPED"
    SENT = "SENT"
    FAILED = "FAILED"


class SourceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    source_event_id: str
    vn_id: str | None = None
    developer_id: str | None = None
    developer_ids: list[str] = Field(default_factory=list)
    developer_names: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    event_type: EventType
    title: str
    summary: str | None = None
    url: HttpUrl
    image_url: HttpUrl | None = None
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    source_event_id: str
    vn_id: str | None = None
    developer_id: str | None = None
    developer_ids: list[str] = Field(default_factory=list)
    developer_names: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    event_type: EventType
    title: str
    summary: str | None = None
    url: str
    image_url: str | None = None
    published_at: datetime | None = None
    discovered_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    normalized_identity: str
    content_hash: str
