# Gal/VN Radar

Gal/VN Radar is a personal Visual Novel / Galgame information monitor. It polls structured sources, converts source data into canonical events, removes duplicates, calculates an explainable relevance score, and sends high-relevance notifications to Telegram.

The current implementation uses VNDB for VN/release-state tracking and Steam News for configured Steam applications. SQLite provides persistence, deterministic scoring, source baselines, seen-item tracking, and cross-source deduplication. Use cron or another external scheduler for periodic execution.

## Architecture

```text
VNDB state ---------------------> SourceAdapter --\
                                                \
Steam News feed ----------------> SourceAdapter ----> SourceEvent / Normalizer
                                                    -> Baseline / Seen-item tracking
                                                    -> SQLite Event Store
                                                    -> Cross-source Deduplication
                                                    -> Relevance Scoring
                                                    -> zh-TW Renderer
                                                    -> Telegram
```

VNDB's official Kana API is query-oriented rather than a news feed. The adapter therefore converts current VN/release state into stable event identities. The first successful VNDB fetch establishes a silent baseline; it does not backfill historical notifications. Later observations can produce `RELEASE_DATE`, `DELAY`, `RELEASED`, or `NEW_TITLE` events. Failed or dry-run deliveries do not advance the source snapshot, so the same transition can be retried safely. Configured developer names are resolved to stable VNDB producer IDs for matching while the configured names remain human-readable.

Steam News is an append-style feed. Each configured Steam app gets its own silent first-sync baseline. Existing announcements are marked seen without notification, and later unseen announcements are classified into canonical event types such as `PATCH`, `DEMO`, `RELEASED`, `DELAY`, `RELEASE_DATE`, `TRAILER`, `DEVLOG`, or `OTHER` before scoring and delivery.

## Setup

Requirements: Python 3.12+ and `uv`.

```bash
uv sync
cp config.example.yaml config.yaml
```

Edit `config.yaml` to choose developers, VNs, preferred tags, and optional Steam app mappings.

## Configuration

```yaml
follow:
  developers:
    - 枕
  visual_novels:
    - v20431
  tags:
    - nakige
  steam_apps:
    - app_id: 123456
      vn_id: v20431
      title: サクラノ刻－櫻の森の下を歩む－
      developer: 枕

preferences:
  languages:
    - ja
    - zh-Hant

notification:
  immediate_threshold: 70
  digest_threshold: 40
```

`visual_novels` accepts a VNDB ID such as `v20431` or a title search string. Developer names are resolved through VNDB's producer API. Preferred tags affect relevance scoring.

`steam_apps` is optional. Each entry explicitly maps a Steam App ID to the canonical VN identity used by Gal/VN Radar. This avoids guessing which Steam product belongs to which VN and allows Steam events to participate in the same scoring and cross-source deduplication rules. `developer` is optional; when present, use the same human-readable name used in `follow.developers`.

Invalid configuration fails at startup with a validation error.

## Cross-source deduplication

Normalized event identity is source-independent. Gal/VN Radar uses the VN identity plus canonical event semantics rather than the source name. This allows, for example, a VNDB `RELEASED` transition and a Steam "now available" announcement for the same VN to collapse into one logical event.

Rules remain deterministic:

- singleton events such as `NEW_TITLE` and `RELEASED` deduplicate by VN + event type;
- release-date changes use VN + event type + normalized release date;
- repeatable feed events such as patches include the normalized news headline, so `Patch 1.1` and `Patch 1.2` remain separate events;
- source + source event ID is still retained for exact same-source replay protection.

No LLM or fuzzy semantic matching is used.

## Telegram bot configuration

Set credentials through environment variables. Do not commit them.

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

See `.env.example` for the variable names. The application does not automatically load `.env`; use your shell, service manager, or secret manager to set environment variables.

When a source provides a valid HTTP(S) image URL, Telegram receives the notification through `sendPhoto` with the zh-TW notification as its caption. Missing or invalid images use `sendMessage`, and a failed photo request falls back to text. The text message remains the source of truth for dry-run output.

## Run a fetch

```bash
uv run python -m gal_radar.main fetch --config config.yaml
```

The default database path is `data/gal_radar.db`.

If `follow.steam_apps` is empty, Steam News is not queried.

## Dry run

```bash
uv run python -m gal_radar.main fetch --dry-run --config config.yaml
```

Dry-run mode prints the final Traditional Chinese Telegram message to stdout, makes no Telegram request, and does not mark an event as delivered. Feed items that would require a notification are not marked seen until a terminal result is reached, so dry-run does not consume future Steam notifications.

## Tests and linting

```bash
uv run pytest
uv run ruff check .
```

Tests use mocked HTTP transports and never require live VNDB, Steam, or Telegram services.

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
4. For state-style sources, use the existing snapshot/change-detection path. For append-style feeds, set `mode = "feed"`, provide a stable `metadata.feed_key`, and let the pipeline baseline existing items before processing new ones.
5. Keep normalization, deduplication, scoring, storage, and Telegram code source-agnostic.
6. Add fixture- or mock-based tests for success, malformed responses, timeouts, and rate limits as applicable.
7. Register the adapter in `main.py` only after it is tested.

itch.io RSS, developer RSS feeds, DLsite, Ci-en, Fantia, developer websites, digest scheduling, and LLM-based semantic deduplication remain deferred.
