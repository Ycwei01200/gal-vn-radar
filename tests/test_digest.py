from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from gal_radar.database import EventRecord, EventStore
from gal_radar.models.event import EventType, NotificationStatus
from gal_radar.notifications.telegram import TelegramNotifier, render_zh_tw_digest
from gal_radar.services.digest import DigestService


class MockNotifier(TelegramNotifier):
    def __init__(self) -> None:
        super().__init__(dry_run=True)
        self.sent_messages: list[str] = []
        self.should_fail = False

    async def send(self, message: str, *, image_url: str | None = None) -> bool:
        if self.should_fail:
            raise RuntimeError("Network error")
        self.sent_messages.append(message)
        return True


def test_render_zh_tw_digest() -> None:
    events = [
        EventRecord(
            id=1,
            event_type=EventType.PATCH.value,
            title="作品 A",
            summary="Patch 1.2 已發布",
            metadata_json={},
        ),
        EventRecord(
            id=2,
            event_type=EventType.TRAILER.value,
            title="作品 B",
            summary="新 PV 公開",
            metadata_json={},
        ),
        EventRecord(
            id=3,
            event_type=EventType.DEVLOG.value,
            title="作品 C",
            summary="官方更新開發進度",
            metadata_json={},
        ),
    ]

    rendered = render_zh_tw_digest(events)
    assert "📚 今日 Gal/VN Radar 摘要" in rendered
    assert "1. 《作品 A》" in rendered
    assert "🛠️ 更新情報" in rendered
    assert "Patch 1.2 已發布" in rendered
    assert "2. 《作品 B》" in rendered
    assert "🎬 宣傳影片" in rendered
    assert "3. 《作品 C》" in rendered
    assert "📝 開發情報" in rendered
    assert "共 3 則你可能感興趣的情報。" in rendered


def test_empty_digest_render() -> None:
    assert render_zh_tw_digest([]) == ""


def test_digest_service_success() -> None:
    async def run() -> None:
        store = EventStore("sqlite:///:memory:")
        store.initialize()

        # Add mock events manually
        for i in range(1, 4):
            record = EventRecord(
                source="test",
                source_event_id=str(i),
                event_type=EventType.PATCH.value,
                title=f"Title {i}",
                url="http://example.com",
                discovered_at=datetime.now(UTC),
                normalized_identity=str(i),
                content_hash=str(i),
                notification_status=NotificationStatus.DIGEST.value,
            )
            with store.engine.begin() as conn:
                from sqlalchemy.orm import Session
                with Session(conn) as session:
                    session.add(record)
                    session.commit()

        notifier = MockNotifier()
        service = DigestService(store, notifier)

        await service.send_digest()

        assert len(notifier.sent_messages) == 1
        assert "Title 1" in notifier.sent_messages[0]
        
        # Check that events were marked as SENT
        events = store.list_events()
        assert len(events) == 3
        assert all(e.notification_status == NotificationStatus.SENT.value for e in events)

    asyncio.run(run())


def test_digest_service_empty_no_telegram_call() -> None:
    async def run() -> None:
        store = EventStore("sqlite:///:memory:")
        store.initialize()
        notifier = MockNotifier()
        service = DigestService(store, notifier)

        await service.send_digest()
        assert len(notifier.sent_messages) == 0

    asyncio.run(run())


def test_digest_service_failure_keeps_status() -> None:
    async def run() -> None:
        store = EventStore("sqlite:///:memory:")
        store.initialize()

        record = EventRecord(
            source="test",
            source_event_id="1",
            event_type=EventType.PATCH.value,
            title="Title",
            url="http://example.com",
            discovered_at=datetime.now(UTC),
            normalized_identity="1",
            content_hash="1",
            notification_status=NotificationStatus.DIGEST.value,
        )
        with store.engine.begin() as conn:
            from sqlalchemy.orm import Session
            with Session(conn) as session:
                session.add(record)
                session.commit()

        notifier = MockNotifier()
        notifier.should_fail = True
        service = DigestService(store, notifier)

        await service.send_digest()

        assert len(notifier.sent_messages) == 0
        events = store.list_events()
        assert len(events) == 1
        assert events[0].notification_status == NotificationStatus.DIGEST.value

    asyncio.run(run())
