from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from gal_radar.config import AppConfig
from gal_radar.database import EventRecord, EventStore
from gal_radar.models.event import NotificationStatus

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5


def configure_logging(log_path: str | Path | None = None) -> Path:
    path = Path(log_path or os.getenv("GAL_RADAR_LOG_PATH", "logs/gal-radar.log"))
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    resolved = path.resolve()
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            try:
                if Path(handler.baseFilename).resolve() == resolved:
                    return path
            except OSError:
                pass

    file_handler = RotatingFileHandler(
        path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    return path


def backup_sqlite(database_path: str | Path, output_dir: str | Path) -> Path:
    source = Path(database_path)
    if not source.exists():
        raise RuntimeError(f"Database file not found: {source}")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    destination = output / f"gal-radar-{stamp}.db"
    counter = 1
    while destination.exists():
        destination = output / f"gal-radar-{stamp}-{counter}.db"
        counter += 1

    try:
        with sqlite3.connect(source) as source_conn, sqlite3.connect(destination) as dest_conn:
            source_conn.backup(dest_conn)
    except sqlite3.Error as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"SQLite backup failed: {exc}") from exc
    return destination


def status_lines(config: AppConfig, store: EventStore) -> list[str]:
    with Session(store.engine) as session:
        total_events = session.scalar(select(func.count()).select_from(EventRecord)) or 0
        digest_count = (
            session.scalar(
                select(func.count())
                .select_from(EventRecord)
                .where(EventRecord.notification_status == NotificationStatus.DIGEST.value)
            )
            or 0
        )
        last_event = session.scalar(select(func.max(EventRecord.discovered_at)))

    with store.engine.connect() as connection:
        baseline_count = connection.execute(text("SELECT COUNT(*) FROM source_baselines")).scalar_one()
        seen_count = connection.execute(text("SELECT COUNT(*) FROM source_seen_items")).scalar_one()

    telegram_ready = bool(
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        and os.getenv("TELEGRAM_CHAT_ID", "").strip()
    )
    configured = (
        f"vndb={len(config.follow.visual_novels)} "
        f"steam={len(config.follow.steam_apps)} "
        f"itch={len(config.follow.itch_apps)} "
        f"rss={len(config.follow.feeds)}"
    )
    return [
        "database=ok",
        f"events={total_events}",
        f"digest_pending={digest_count}",
        f"last_event={last_event.isoformat() if last_event else 'none'}",
        f"baselines={baseline_count}",
        f"seen_items={seen_count}",
        f"configured_sources={configured}",
        f"telegram={'configured' if telegram_ready else 'missing'}",
    ]
