from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from gal_radar.adapters.vndb import VNDBAdapter
from gal_radar.config import TelegramConfig, load_config
from gal_radar.database import EventStore
from gal_radar.notifications.telegram import TelegramNotifier
from gal_radar.services.pipeline import Pipeline


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
    return parser


async def run_fetch(*, config_path: str, database_path: str, dry_run: bool) -> None:
    config = load_config(config_path)
    store = EventStore(f"sqlite:///{Path(database_path)}")
    store.initialize()

    if dry_run:
        notifier = TelegramNotifier(dry_run=True)
    else:
        telegram = TelegramConfig.from_environment()
        notifier = TelegramNotifier(bot_token=telegram.bot_token, chat_id=telegram.chat_id)

    pipeline = Pipeline(
        config=config,
        store=store,
        adapters=[VNDBAdapter()],
        notifier=notifier,
    )
    await pipeline.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args()
    if args.command == "fetch":
        asyncio.run(
            run_fetch(
                config_path=args.config,
                database_path=args.database,
                dry_run=args.dry_run,
            )
        )


if __name__ == "__main__":
    main()
