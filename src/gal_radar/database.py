from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    or_,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from gal_radar.models.event import NormalizedEvent, NotificationStatus
from gal_radar.services.ranking import ScoreResult


class Base(DeclarativeBase):
    pass


class EventRecord(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("source", "source_event_id", name="uq_source_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    vn_id: Mapped[str | None] = mapped_column(String(32))
    developer_id: Mapped[str | None] = mapped_column(String(32))
    developer_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    normalized_identity: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    relevance_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    relevance_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    notification_status: Mapped[str] = mapped_column(
        String(32), default=NotificationStatus.PENDING.value, nullable=False
    )


class EventStore:
    def __init__(self, database_url: str = "sqlite:///data/gal_radar.db") -> None:
        if database_url.startswith("sqlite:///"):
            raw_path = database_url.removeprefix("sqlite:///")
            if raw_path and raw_path != ":memory:":
                Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(database_url, future=True)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)

    def find_equivalent(self, event: NormalizedEvent) -> EventRecord | None:
        with Session(self.engine) as session:
            statement = select(EventRecord).where(
                or_(
                    (EventRecord.source == event.source)
                    & (EventRecord.source_event_id == event.source_event_id),
                    EventRecord.normalized_identity == event.normalized_identity,
                    EventRecord.content_hash == event.content_hash,
                )
            )
            return session.scalars(statement).first()

    def add(self, event: NormalizedEvent, score: ScoreResult) -> EventRecord:
        record = EventRecord(
            source=event.source,
            source_event_id=event.source_event_id,
            vn_id=event.vn_id,
            developer_id=event.developer_id,
            developer_names=event.developer_names,
            tags=event.tags,
            event_type=event.event_type.value,
            title=event.title,
            summary=event.summary,
            url=event.url,
            published_at=event.published_at,
            discovered_at=event.discovered_at,
            normalized_identity=event.normalized_identity,
            content_hash=event.content_hash,
            metadata_json=event.metadata,
            relevance_score=score.score,
            relevance_reasons=list(score.reasons),
            notification_status=NotificationStatus.PENDING.value,
        )
        with Session(self.engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            session.expunge(record)
        return record

    def update_notification_status(self, event_id: int, status: NotificationStatus) -> None:
        with Session(self.engine) as session:
            record = session.get(EventRecord, event_id)
            if record is None:
                raise RuntimeError(f"Event not found: {event_id}")
            record.notification_status = status.value
            session.commit()

    def list_events(self) -> list[EventRecord]:
        with Session(self.engine) as session:
            records = list(session.scalars(select(EventRecord).order_by(EventRecord.id)))
            for record in records:
                session.expunge(record)
            return records


def utc_now() -> datetime:
    return datetime.now(UTC)
