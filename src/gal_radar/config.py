from __future__ import annotations

import os
from pathlib import Path

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

    @property
    def resolved_developer_ids(self) -> list[str]:
        return list(self._resolved_developer_ids)

    def set_resolved_developer_ids(self, developer_ids: list[str]) -> None:
        resolved_ids: list[str] = []
        seen_ids: set[str] = set()
        for developer_id in developer_ids:
            stripped = developer_id.strip()
            if stripped and stripped not in seen_ids:
                seen_ids.add(stripped)
                resolved_ids.append(stripped)
        self._resolved_developer_ids = resolved_ids


class PreferencesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    languages: list[str] = Field(default_factory=lambda: ["ja", "zh-Hant"])


class NotificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    immediate_threshold: int = Field(default=70, ge=0)
    digest_threshold: int = Field(default=40, ge=0)

    @model_validator(mode="after")
    def validate_thresholds(self) -> NotificationConfig:
        if self.digest_threshold > self.immediate_threshold:
            raise ValueError("digest_threshold must be <= immediate_threshold")
        return self


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    followed_vn: int = 100
    followed_developer: int = 60
    preferred_tag: int = 10
    event_type: dict[EventType, int] = Field(
        default_factory=lambda: {
            EventType.NEW_TITLE: 40,
            EventType.RELEASE_DATE: 30,
            EventType.RELEASED: 30,
            EventType.DEMO: 25,
            EventType.DELAY: 20,
        }
    )


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    follow: FollowConfig = Field(default_factory=FollowConfig)
    preferences: PreferencesConfig = Field(default_factory=PreferencesConfig)
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
