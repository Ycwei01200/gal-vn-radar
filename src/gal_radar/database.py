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
    inspect,
    or_,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from gal_radar.models.event import NormalizedEvent, NotificationStatus
from gal_radar.services.change_detection import SourceSnapshotState
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
    image_url: Mapped[str | None] = mapped_column(Text)
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


class SourceSnapshotRecord(Base):
    __tablename__ = "source_snapshots"

    source: Mapped[str] = mapped_column(String(50), primary_key=True)
    entity_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    developer_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    release_date: Mapped[str | None] = mapped_column(String(10))
    release_state: Mapped[str] = mapped_column(String(32), nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceBaselineRecord(Base):
    __tablename__ = "source_baselines"

    source: Mapped[str] = mapped_column(String(100), primary_key=True)
    initialized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceSeenItemRecord(Base):
    __tablename__ = "source_seen_items"

    source: Mapped[str] = mapped_column(String(50), primary_key=True)
    source_event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventStore:
    def __init__(self, database_url: str = "sqlite:///data/gal_radar.db") -> None:
        if database_url.startswith("sqlite:///"):
            raw_path = database_url.removeprefix("sqlite:///")
            if raw_path and raw_path != ":memory:":
                Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(database_url, future=True)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
        if self.engine.dialect.name != "sqlite":
            return
        columns = {column["name"] for column in inspect(self.engine).get_columns("events")}
        if "image_url" not in columns:
            with self.engine.begin() as connection:
                connection.execute(text("ALTER TABLE events ADD COLUMN image_url TEXT"))

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
            image_url=event.image_url,
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

    def get_snapshot(self, source: str, entity_key: str) -> SourceSnapshotState | None:
        with Session(self.engine) as session:
            record = session.get(
                SourceSnapshotRecord,
                {"source": source, "entity_key": entity_key},
            )
            if record is None:
                return None
            return _snapshot_from_record(record)

    def save_snapshot(self, source: str, snapshot: SourceSnapshotState) -> None:
        with Session(self.engine) as session:
            record = session.get(
                SourceSnapshotRecord,
                {"source": source, "entity_key": snapshot.entity_key},
            )
            if record is None:
                record = SourceSnapshotRecord(
                    source=source,
                    entity_key=snapshot.entity_key,
                )
                session.add(record)
            record.title = snapshot.title
            record.developer_ids = list(snapshot.developer_ids)
            record.release_date = (
                snapshot.release_date.isoformat() if snapshot.release_date is not None else None
            )
            record.release_state = snapshot.release_state
            record.image_url = snapshot.image_url
            record.observed_at = snapshot.observed_at
            session.commit()

    def is_baseline_initialized(self, source: str) -> bool:
        with Session(self.engine) as session:
            return session.get(SourceBaselineRecord, source) is not None

    def mark_baseline_initialized(
        self,
        source: str,
        *,
        initialized_at: datetime | None = None,
    ) -> None:
        timestamp = initialized_at or utc_now()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("initialized_at must be timezone-aware")
        with Session(self.engine) as session:
            if session.get(SourceBaselineRecord, source) is None:
                session.add(
                    SourceBaselineRecord(
                        source=source,
                        initialized_at=timestamp.astimezone(UTC),
                    )
                )
                session.commit()

    def is_source_item_seen(self, source: str, source_event_id: str) -> bool:
        with Session(self.engine) as session:
            return (
                session.get(
                    SourceSeenItemRecord,
                    {"source": source, "source_event_id": source_event_id},
                )
                is not None
            )

    def mark_source_item_seen(
        self,
        source: str,
        source_event_id: str,
        *,
        seen_at: datetime | None = None,
    ) -> None:
        timestamp = seen_at or utc_now()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("seen_at must be timezone-aware")
        with Session(self.engine) as session:
            key = {"source": source, "source_event_id": source_event_id}
            if session.get(SourceSeenItemRecord, key) is None:
                session.add(
                    SourceSeenItemRecord(
                        source=source,
                        source_event_id=source_event_id,
                        seen_at=timestamp.astimezone(UTC),
                    )
                )
                session.commit()

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


def _snapshot_from_record(record: SourceSnapshotRecord) -> SourceSnapshotState:
    from gal_radar.services.change_detection import parse_release_date

    observed_at = record.observed_at
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    return SourceSnapshotState(
        entity_key=record.entity_key,
        title=record.title,
        developer_ids=tuple(record.developer_ids),
        release_date=parse_release_date(record.release_date),
        release_state=record.release_state,
        image_url=record.image_url,
        observed_at=observed_at,
    )
