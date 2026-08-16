from __future__ import annotations

from typing import Protocol

from gal_radar.config import FollowConfig
from gal_radar.models.event import SourceEvent


class SourceAdapter(Protocol):
    name: str

    async def fetch_events(self, follow: FollowConfig) -> list[SourceEvent]: ...


class SourceAdapterError(RuntimeError):
    """Raised when an external source cannot be queried safely."""
