from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from gal_radar.adapters.itch import ItchAdapter
from gal_radar.adapters.rss import RSSAdapter
from gal_radar.adapters.steam import SteamNewsAdapter
from gal_radar.adapters.vndb import VNDBAdapter
from gal_radar.config import TelegramConfig, load_config
from gal_radar.database import EventStore
from gal_radar.notifications.telegram import TelegramNotifier
from gal_radar.services.digest import DigestService
from gal_radar.services.pipeline import Pipeline
from gal_radar.services.runtime import backup_sqlite, configure_logging, status_lines

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gal-radar")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch", help="Fetch, score, store, and notify new events")
    fetch.add_argument(
        "--dry-run",
        action="store_true",
        help="Render notifications without Telegram",
    )
    fetch.add_argument("--config", default="config.yaml", help="Path to YAML configuration")
    fetch.add_argument("--database", default="data/gal_radar.db", help="Path to SQLite database")

    digest = subparsers.add_parser("digest", help="Send daily digest to Telegram")
    digest.add_argument("--dry-run", action="store_true", help="Render digest without Telegram")
    digest.add_argument("--config", default="config.yaml", help="Path to YAML configuration")
    digest.add_argument("--database", default="data/gal_radar.db", help="Path to SQLite database")

    status = subparsers.add_parser("status", help="Inspect local Gal/VN Radar health")
    status.add_argument("--config", default="config.yaml", help="Path to YAML configuration")
    status.add_argument("--database", default="data/gal_radar.db", help="Path to SQLite database")

    doctor = subparsers.add_parser("doctor", help="Diagnose local configuration and runtime state")
    doctor.add_argument("--config", default="config.yaml", help="Path to YAML configuration")
    doctor.add_argument("--database", default="data/gal_radar.db", help="Path to SQLite database")

    test_telegram = subparsers.add_parser(
        "test-telegram",
        help="Send a single explicit Telegram connectivity test",
    )
    test_telegram.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the test message without Telegram",
    )

    backup = subparsers.add_parser("backup", help="Create a consistent SQLite backup")
    backup.add_argument("--database", default="data/gal_radar.db", help="Path to SQLite database")
    backup.add_argument("--output", default="backups", help="Backup output directory")
    return parser


def _store(database_path: str) -> EventStore:
    store = EventStore(f"sqlite:///{Path(database_path)}")
    store.initialize()
    return store


async def run_fetch(*, config_path: str, database_path: str, dry_run: bool) -> int:
    config = load_config(config_path)
    store = _store(database_path)
    notifier = _notifier(dry_run)
    adapters = [VNDBAdapter()]
    if config.follow.steam_apps:
        adapters.append(SteamNewsAdapter())
    if config.follow.itch_apps:
        adapters.append(ItchAdapter())
    if config.follow.feeds:
        adapters.append(RSSAdapter())

    pipeline = Pipeline(config=config, store=store, adapters=adapters, notifier=notifier)
    await pipeline.run()
    if pipeline.successful_source_count == 0 and pipeline.failed_source_count > 0:
        logger.error("fetch failed: all configured adapters failed")
        return 1
    return 0


async def run_digest(*, config_path: str, database_path: str, dry_run: bool) -> int:
    config = load_config(config_path)
    store = _store(database_path)
    service = DigestService(
        store=store,
        notifier=_notifier(dry_run),
        source_priority=config.preferences.source_priority,
    )
    await service.send_digest()
    return 0


def _notifier(dry_run: bool) -> TelegramNotifier:
    if dry_run:
        return TelegramNotifier(dry_run=True)
    telegram = TelegramConfig.from_environment()
    return TelegramNotifier(bot_token=telegram.bot_token, chat_id=telegram.chat_id)


def run_status(*, config_path: str, database_path: str) -> int:
    config = load_config(config_path)
    store = _store(database_path)
    for line in status_lines(config, store):
        print(line)
    return 0


def run_doctor(*, config_path: str, database_path: str) -> int:
    config = load_config(config_path)
    store = _store(database_path)
    print("Gal/VN Radar doctor")
    for line in status_lines(config, store):
        print(f"OK {line}")

    warnings: list[str] = []
    source_count = (
        len(config.follow.visual_novels)
        + len(config.follow.developers)
        + len(config.follow.steam_apps)
        + len(config.follow.itch_apps)
        + len(config.follow.feeds)
    )
    if source_count == 0:
        warnings.append("no follow targets are configured")
    if not os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        warnings.append("TELEGRAM_BOT_TOKEN is missing")
    if not os.getenv("TELEGRAM_CHAT_ID", "").strip():
        warnings.append("TELEGRAM_CHAT_ID is missing")
    if not config.notification.enabled_event_types:
        warnings.append("all event types are disabled")

    if warnings:
        for warning in warnings:
            print(f"WARN {warning}")
    else:
        print("OK no operational warnings")
    return 0


async def run_test_telegram(*, dry_run: bool) -> int:
    message = "✅ Gal/VN Radar Telegram 測試成功"
    delivered = await _notifier(dry_run).send(message)
    if dry_run:
        return 0
    return 0 if delivered else 1


def run_backup(*, database_path: str, output: str) -> int:
    destination = backup_sqlite(database_path, output)
    print(destination)
    return 0


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    try:
        if args.command == "fetch":
            code = asyncio.run(
                run_fetch(
                    config_path=args.config,
                    database_path=args.database,
                    dry_run=args.dry_run,
                )
            )
        elif args.command == "digest":
            code = asyncio.run(
                run_digest(
                    config_path=args.config,
                    database_path=args.database,
                    dry_run=args.dry_run,
                )
            )
        elif args.command == "status":
            code = run_status(config_path=args.config, database_path=args.database)
        elif args.command == "doctor":
            code = run_doctor(config_path=args.config, database_path=args.database)
        elif args.command == "test-telegram":
            code = asyncio.run(run_test_telegram(dry_run=args.dry_run))
        elif args.command == "backup":
            code = run_backup(database_path=args.database, output=args.output)
        else:
            code = 2
    except Exception as exc:
        logger.exception("command failed command=%s error=%s", args.command, type(exc).__name__)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
