# Gal/VN Radar

Gal/VN Radar is a personal Visual Novel / Galgame information monitor. It polls structured sources, converts source data into canonical events, removes duplicates, calculates an explainable relevance score, and sends high-relevance notifications to Telegram.

The MVP uses VNDB as its primary source, SQLite for persistence, deterministic scoring, and cron or another external scheduler for periodic execution.

## Architecture

```text
VNDB
  -> SourceAdapter
  -> SourceEvent / Normalizer
  -> SQLite Event Store
  -> Deduplication
  -> Relevance Scoring
  -> zh-TW Renderer
  -> Telegram
```

VNDB's official Kana API is query-oriented rather than a news feed. The adapter therefore converts current VN/release state into stable event identities. SQLite persistence makes repeated runs idempotent and allows changed states, such as a changed release date, to become new events.

## Setup

Requirements: Python 3.12+ and `uv`.

```bash
uv sync
cp config.example.yaml config.yaml
```

Edit `config.yaml` to choose developers, VNs, and preferred tags.

## Configuration

```yaml
follow:
  developers:
    - 枕
  visual_novels:
    - v20431
  tags:
    - nakige

preferences:
  languages:
    - ja
    - zh-Hant

notification:
  immediate_threshold: 70
  digest_threshold: 40
```

`visual_novels` accepts a VNDB ID such as `v20431` or a title search string. Developer names are resolved through VNDB's producer API. Preferred tags affect relevance scoring.

Invalid configuration fails at startup with a validation error.

## Telegram bot configuration

Set credentials through environment variables. Do not commit them.

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

See `.env.example` for the variable names. The application does not automatically load `.env`; use your shell, service manager, or secret manager to set environment variables.

## Run a fetch

```bash
uv run python -m gal_radar.main fetch --config config.yaml
```

The default database path is `data/gal_radar.db`.

## Dry run

```bash
uv run python -m gal_radar.main fetch --dry-run --config config.yaml
```

Dry-run mode prints the final Traditional Chinese Telegram message to stdout, makes no Telegram request, and does not mark the event as delivered.

## Tests and linting

```bash
uv run pytest
uv run ruff check .
```

Tests use mocked HTTP transports and never require live VNDB or Telegram services.

## Cron example

Run every 30 minutes:

```cron
*/30 * * * * cd /path/to/gal-vn-radar && /path/to/uv run python -m gal_radar.main fetch --config config.yaml >> data/cron.log 2>&1
```

Use absolute paths in cron and provide the Telegram environment variables through the cron environment or a wrapper script.

## Adding a new source

1. Add an adapter under `src/gal_radar/adapters/`.
2. Implement the `SourceAdapter` protocol from `adapters/base.py`.
3. Convert all source-specific responses into `SourceEvent` instances inside the adapter.
4. Keep normalization, deduplication, scoring, storage, and Telegram code source-agnostic.
5. Add fixture- or mock-based tests for success, malformed responses, timeouts, and rate limits as applicable.
6. Register the adapter in `main.py` only after it is tested.

Steam News, itch.io RSS, developer RSS feeds, DLsite, Ci-en, Fantia, and developer websites are intentionally deferred until the VNDB-first MVP is stable.
