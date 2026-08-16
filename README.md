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
    - visual arts
    - yuzusoft
  visual_novels:
    - v20431
  tags:
    - science fiction
  steam_apps:
    - app_id: 123450
      vn_id: v123
      title: "Example Game"
  itch_apps:
    - url: "https://example.itch.io/game"
      vn_id: "v123"
      title: "Example Game"
  feeds:
    - url: "https://example.com/rss.xml"
      vn_id: "v123"

preferences:
  languages:
    - ja
    - zh-Hant

notification:
  immediate_threshold: 70
  digest_threshold: 40
```

`visual_novels` accepts a VNDB ID such as `v20431` or a title search string. Developer names are resolved through VNDB's producer API. Preferred tags affect relevance scoring.

## 支援情報來源

- **VNDB**: 提供新作、發售日異動、發售等情報 (Snapshot 模式)。
- **Steam**: 支援追蹤特定 Steam App 頁面的新聞公告 (Feed 模式)。
- **itch.io**: 支援追蹤特定遊戲的 itch.io Devlog (Feed 模式)。
- **官方 RSS**: 支援自訂 RSS/Atom 來源 (Feed 模式)。

> **注意：** 關於 DLsite、Ci-en 及 Fantia，目前因為這些平台缺乏官方公開 API 及 RSS 訂閱，且通常需要帳號登入或涉及反爬蟲機制 (Cloudflare 等)，因此暫不支援 (Deferred)。若未來有官方結構化介面，將再行評估。by Gal/VN Radar. This avoids guessing which Steam product belongs to which VN and allows Steam events to participate in the same scoring and cross-source deduplication rules. `developer` is optional; when present, use the same human-readable name used in `follow.developers`.

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

DLsite, Ci-en, Fantia, developer websites, digest scheduling, and LLM-based semantic deduplication remain deferred.

## Manual RSS E2E Validation

To manually validate a live RSS feed without spamming yourself with historical items:

1. Configure a single RSS feed in your `config.yaml` using a real URL.
2. Run `uv run python -m gal_radar.main fetch --config config.yaml` to establish the silent baseline. This fetches the feed and marks all existing items as seen, saving to `source_baselines` and `source_seen_items`.
3. Run the same fetch command again. The system will skip the seen items and produce no new notifications.
4. You can then use the `--dry-run` flag in the future to safely preview notifications if a new item is published to the feed.

## Operational Hardening & Error Isolation

- **Provenance & Corroboration**: If multiple sources report the same logical event (e.g., VNDB, Steam, and an official RSS feed), the system preserves the primary event while recording corroborating sources. Telegram notifications will display all sources (e.g., `來源：VNDB、Steam、官方 RSS`).
- **Error Isolation**: The pipeline isolates failures at the smallest sensible unit. A failure in one Steam app or one RSS feed will log the error but allow other apps and feeds to process successfully. A failed source does not initialize its baseline, nor does it mark any unseen items as seen, ensuring safe retries on the next fetch.
- **Digest Batching**: Digests are deterministically sorted (highest relevance score and most recent publish date first) and split into batches of 10 events per message to avoid exceeding Telegram message limits. Each batch is individually tracked and marked as `SENT` only upon successful delivery.
