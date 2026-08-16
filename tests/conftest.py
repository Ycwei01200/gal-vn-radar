from __future__ import annotations

import pytest

from gal_radar.config import AppConfig
from gal_radar.database import EventStore


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "follow": {
                "developers": ["枕"],
                "visual_novels": ["v20431"],
                "tags": ["nakige"],
            },
            "notification": {
                "immediate_threshold": 70,
                "digest_threshold": 40,
            },
        }
    )


@pytest.fixture
def event_store(tmp_path) -> EventStore:
    store = EventStore(f"sqlite:///{tmp_path / 'events.db'}")
    store.initialize()
    return store
