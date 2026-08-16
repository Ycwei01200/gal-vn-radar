from __future__ import annotations

import sqlite3
from pathlib import Path

from gal_radar.config import AppConfig
from gal_radar.database import EventStore
from gal_radar.services.runtime import LOG_BACKUP_COUNT, LOG_MAX_BYTES, backup_sqlite, status_lines


def test_backup_sqlite_creates_valid_copy(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('ok')")
        connection.commit()

    backup = backup_sqlite(source, tmp_path / "backups")

    assert backup.exists()
    assert backup != source
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("ok",)


def test_status_does_not_require_telegram_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    store = EventStore(f"sqlite:///{tmp_path / 'status.db'}")
    store.initialize()

    lines = status_lines(AppConfig(), store)

    assert "database=ok" in lines
    assert "telegram=missing" in lines


def test_log_rotation_policy_is_bounded() -> None:
    assert LOG_MAX_BYTES == 5 * 1024 * 1024
    assert LOG_BACKUP_COUNT == 5
