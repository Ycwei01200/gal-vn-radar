from __future__ import annotations

from typing import Protocol


class NotificationSink(Protocol):
    async def send(self, message: str, *, image_url: str | None = None) -> bool:
        """Send a message and return True only after confirmed delivery."""
        ...
