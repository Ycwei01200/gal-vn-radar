from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PrivateAttr,
    ValidationError,
    model_validator,
)

from gal_radar.models.event import EventType


class SteamAppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_id: int = Field(gt=0)
    vn_id: str
    title: str
    developer: str | None = None
    developer_ids: list[str] = Field(default_factory=list)


class ItchAppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    vn_id: str | None = None
    title: str | None = None
    developer: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> ItchAppConfig:
        if not self.vn_id and not self.developer:
            raise ValueError("Itch app must specify either vn_id or developer")
        return self


class FeedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    vn_id: str | None = None
    title: str | None = None
    developer: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> FeedConfig:
        if not self.vn_id and not self.developer:
            raise ValueError("Feed must specify either vn_id or developer")
        return self


class FollowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    developers: list[str] = Field(default_factory=list)
    visual_novels: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    steam_apps: list[SteamAppConfig] = Field(default_factory=list)
    itch_apps: list[ItchAppConfig] = Field(default_factory=list)
    feeds: list[FeedConfig] = Field(default_factory=list)
    _resolved_developer_ids: list[str] = PrivateAttr(default_factory=list)
    _discovered_vn_ids: set[str] = PrivateAttr(default_factory=set)

    @property
    def resolved_developer_ids(self) -> list[str]:
        return list(self._resolved_developer_ids)

    @property
    def discovered_vn_ids(self) -> set[str]:
        return set(self._discovered_vn_ids)

    def set_resolved_developer_ids(self, developer_ids: list[str]) -> None:
        resolved_ids: list[str] = []
        seen_ids: set[str] = set()
        for developer_id in developer_ids:
            stripped = developer_id.strip()
            if stripped and stripped not in seen_ids:
                seen_ids.add(stripped)
                resolved_ids.append(stripped)
        self._resolved_developer_ids = resolved_ids

    def add_discovered_vn(self, vn_id: str) -> None:
        stripped = vn_id.strip().lower()
        if stripped:
            self._discovered_vn_ids.add(stripped)

    def add_discovered_steam_app(self, app: SteamAppConfig) -> None:
        for index, existing in enumerate(self.steam_apps):
            if existing.app_id != app.app_id:
                continue
            merged_ids = list(existing.developer_ids)
            for developer_id in app.developer_ids:
                if developer_id not in merged_ids:
                    merged_ids.append(developer_id)
            self.steam_apps[index] = existing.model_copy(
                update={
                    "vn_id": existing.vn_id or app.vn_id,
                    "title": existing.title or app.title,
                    "developer": existing.developer or app.developer,
                    "developer_ids": merged_ids,
                }
            )
            return
        self.steam_apps.append(app)

    def add_discovered_itch_app(self, app: ItchAppConfig) -> None:
        target = str(app.url).rstrip("/").casefold()
        if any(str(existing.url).rstrip("/").casefold() == target for existing in self.itch_apps):
            return
        self.itch_apps.append(app)

    def add_discovered_feed(self, feed: FeedConfig) -> None:
        target = str(feed.url).casefold()
        if any(str(existing.url).casefold() == target for existing in self.feeds):
            return
        self.feeds.append(feed)


class PreferencesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    languages: list[str] = Field(default_factory=lambda: ["ja", "zh-Hant"])
    source_priority: list[str] = Field(
        default_factory=lambda: ["vndb", "steam", "itch.io", "rss"]
    )


class DiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    vndb_results: int = Field(default=50, ge=1, le=100)
    steam_from_vndb_extlinks: bool = True
    itch_from_vndb_extlinks: bool = True
    feeds_from_vndb_extlinks: bool = True


class NotificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    immediate_threshold: int = Field(default=70, ge=0)
    digest_threshold: int = Field(default=40, ge=0)
    enabled_event_types: list[EventType] = Field(default_factory=lambda: list(EventType))
    max_snapshot_release_age_days: int = Field(default=30, ge=0)
    image_delivery: Literal["photo", "document"] = "document"

    @model_validator(mode="after")
    def validate_thresholds(self) -> NotificationConfig:
        if self.digest_threshold > self.immediate_threshold:
            raise ValueError("digest_threshold must be <= immediate_threshold")
        if len(set(self.enabled_event_types)) != len(self.enabled_event_types):
            raise ValueError("enabled_event_types must not contain duplicates")
        return self


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    followed_vn: int = 100
    discovered_vn: int = 40
    followed_developer: int = 60
    preferred_tag: int = 10
    event_type: dict[EventType, int] = Field(
        default_factory=lambda: {
            EventType.NEW_TITLE: 40,
            EventType.RELEASE_DATE: 30,
            EventType.RELEASED: 30,
            EventType.DEMO: 25,
            EventType.DELAY: 20,
            EventType.LOCALIZATION: 20,
            EventType.PATCH: 10,
            EventType.TRAILER: 10,
            EventType.DEVLOG: 10,
        }
    )


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    follow: FollowConfig = Field(default_factory=FollowConfig)
    preferences: PreferencesConfig = Field(default_factory=PreferencesConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)


class TelegramConfig(BaseModel):
    bot_token: str
    chat_id: str

    @classmethod
    def from_environment(cls) -> TelegramConfig:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        missing = [
            name
            for name, value in (
                ("TELEGRAM_BOT_TOKEN", token),
                ("TELEGRAM_CHAT_ID", chat_id),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
        return cls(bot_token=token, chat_id=chat_id)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise RuntimeError(f"Configuration file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Invalid YAML in configuration file: {config_path}: {exc}") from exc

    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid configuration in {config_path}: {exc}") from exc
