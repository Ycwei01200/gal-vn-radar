# Gal/VN Radar

Gal/VN Radar is a personal Visual Novel / Galgame information monitor. It polls structured sources, converts source data into canonical events, deduplicates them across sources, calculates an explainable relevance score, and sends high-relevance notifications or digests to Telegram.

## v1 status

Gal/VN Radar v1 is deployable on Windows with CLI commands scheduled by Windows Task Scheduler.

Implemented sources:

- **VNDB**: snapshot-based VN and release-state tracking plus automatic recent-VN discovery.
- **Steam News**: automatically mapped from VNDB external links when available; explicit mappings remain supported.
- **itch.io**: automatically mapped from VNDB itch.io links when available; explicit mappings remain supported.
- **RSS/Atom**: automatically picked up when VNDB exposes a direct feed-like external link; explicit public feeds remain supported.

Deferred sources:

- DLsite
- Ci-en
- Fantia

These are deferred because the project intentionally avoids authenticated scraping, browser automation, CAPTCHA/Cloudflare bypasses, and brittle arbitrary HTML parsing.

## Architecture

```text
VNDB recent VN discovery
        |
        +--> VNDB snapshot tracking
        +--> Steam extlink -> Steam News
        +--> itch.io extlink -> devlog RSS
        +--> feed-like extlink -> RSS/Atom
                              |
                              v
                         SourceEvent
                              -> normalize
                              -> baseline / seen items
                              -> SQLite Event Store
                              -> cross-source dedup
                              -> provenance
                              -> relevance scoring
                              -> zh-TW renderer
                              -> Telegram / Digest
```

VNDB uses snapshot/change-detection semantics. Its first successful fetch establishes a silent baseline. Later observations can produce `RELEASE_DATE`, `DELAY`, `RELEASED`, or `NEW_TITLE` events.

Steam, itch.io, and generic RSS/Atom are append-style feeds. Their first successful fetch marks existing entries seen without historical notification spam. Later unseen entries are processed exactly once.

## Setup

Requirements: Python 3.12+ and `uv`.

```powershell
uv sync
Copy-Item config.example.yaml config.yaml
```

Keep `config.yaml` local and untracked.

## Configuration

Auto-discovery is enabled by default. The manual `follow` mappings are overrides and preference hints rather than a prerequisite.

```yaml
follow:
  developers:
    - visual arts
    - yuzusoft
  visual_novels: []
  tags:
    - science fiction
  steam_apps: []
  itch_apps: []
  feeds: []

discovery:
  enabled: true
  vndb_results: 50
  steam_from_vndb_extlinks: true
  itch_from_vndb_extlinks: true
  feeds_from_vndb_extlinks: true

preferences:
  languages:
    - ja
    - zh-Hant

notification:
  immediate_threshold: 70
  digest_threshold: 40
  max_snapshot_release_age_days: 30
```

`visual_novels` accepts a VNDB ID or title search string. Developer names are resolved through VNDB producer IDs for stable matching. Automatic source mapping relies on VNDB external-link identifiers and URLs; it deliberately avoids fuzzy title matching.

### Auto-discovery scoring

Explicitly followed VNs keep the strongest priority. Auto-discovered VNs receive a smaller relevance boost only for meaningful event types:

- `NEW_TITLE`, `RELEASE_DATE`, `RELEASED`, `DELAY`, `DEMO`, `LOCALIZATION`: higher priority.
- `PATCH`, `TRAILER`, `DEVLOG`: normally digest-level.
- `OTHER`: no auto-discovery boost, avoiding notification spam.

## Telegram configuration

Set credentials as environment variables. Never commit them.

```powershell
[Environment]::SetEnvironmentVariable(
    "TELEGRAM_BOT_TOKEN",
    "<token>",
    "User"
)
[Environment]::SetEnvironmentVariable(
    "TELEGRAM_CHAT_ID",
    "<chat-id>",
    "User"
)
```

Open a new PowerShell after setting them. The deployment runners also re-read these values from the persistent User environment when needed.

## Commands

Fetch:

```powershell
uv run python -m gal_radar.main fetch --config config.yaml --database data/gal_radar.db
```

Safe preview:

```powershell
uv run python -m gal_radar.main fetch --dry-run --config config.yaml --database data/gal_radar.db
```

Digest:

```powershell
uv run python -m gal_radar.main digest --config config.yaml --database data/gal_radar.db
```

Status:

```powershell
uv run python -m gal_radar.main status --config config.yaml --database data/gal_radar.db
```

Backup:

```powershell
uv run python -m gal_radar.main backup --database data/gal_radar.db --output backups
```

## Cross-source deduplication and provenance

Normalized event identity is source-independent. The system uses VN identity plus canonical event semantics rather than source name. For example, a VNDB `RELEASED` transition and a Steam or RSS release announcement for the same VN can collapse into one logical event.

When multiple sources corroborate the same logical event, the canonical event is retained and additional source references are recorded. Telegram can render source labels such as:

```text
來源：VNDB、Steam、官方 RSS
```

No LLM or fuzzy semantic matching is used.

## Telegram behavior

High-relevance events are delivered immediately. Medium-relevance events enter the digest queue. Digest messages are ordered deterministically and split into batches of at most 10 events. A batch is marked `SENT` only after confirmed Telegram delivery; later batches remain retryable if a partial digest delivery fails.

When a source provides a stable HTTP(S) image URL, Telegram uses `sendPhoto`; failures fall back to text. Bot tokens are redacted from logs.

## Operational reliability

- Source failures are isolated so healthy adapters can continue.
- Failed feeds do not initialize baselines or consume unseen items.
- SQLite preserves baselines, seen-item state, dedup state, and notifications across process restarts.
- Runtime logs rotate at 5 MiB with five backups.
- SQLite backups use the SQLite backup API rather than a blind file copy.
- `status` performs local health inspection without external API calls or Telegram sends.

## Windows deployment

The v1 deployment model is CLI + Windows Task Scheduler. No internal daemon or scheduler is used.

One-command task installation:

```powershell
.\scripts\install-scheduled-tasks.ps1
```

Default schedule:

- `GalVNRadar-Fetch`: every 30 minutes.
- `GalVNRadar-Digest`: daily at 20:00 local time.
- failure retry: after 5 minutes, up to 3 attempts.
- overlapping runs: ignored.
- execution time limit: 15 minutes.

Inspect tasks:

```powershell
.\scripts\check-scheduled-tasks.ps1
```

See [`docs/windows-deployment.md`](docs/windows-deployment.md) for deployment and restore instructions.

## Short soak validation

```powershell
.\scripts\soak-test.ps1 -Iterations 10 -IntervalSeconds 60 -DryRun
```

The project has been exercised through repeated live VNDB polling without fatal failure. A multi-day production soak is still an operational confidence exercise rather than a v1 feature requirement.

See [`docs/phase3-soak-checklist.md`](docs/phase3-soak-checklist.md).

## Final verification

Run:

```powershell
.\scripts\verify-v1.ps1
```

It checks automated tests, Ruff, `git diff --check`, local status, runner dry-runs, scheduled-task presence, and recent log availability without intentionally sending Telegram notifications.

## Tests

```powershell
uv run pytest
uv run ruff check .
git diff --check
```

Automated tests use mocks/fixtures for external network behavior. Live source and Telegram checks are manual operational validation and must not be inferred from unit tests.

## Adding a new source

1. Add an adapter under `src/gal_radar/adapters/`.
2. Implement the existing `SourceAdapter` protocol.
3. Convert source data to `SourceEvent`.
4. Use snapshot mode for state sources or `mode = "feed"` for append-style sources.
5. Reuse baseline, seen-item, normalization, dedup, provenance, scoring, and notification services.
6. Add fixture/mock-based tests.
7. Register the adapter only after tests pass.

Do not introduce authenticated scraping or browser-automation workarounds merely to increase source count.
