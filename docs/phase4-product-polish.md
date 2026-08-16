# Phase 4 — Product Polish

Phase 4 intentionally focuses on product usability without changing the deployment model or adding a web UI, LLM, Docker stack, or background bot listener.

## Features

### Event-type notification preferences

`notification.enabled_event_types` controls which canonical event types are eligible for Telegram or Digest delivery. Disabled event types are still stored and deduplicated, but are marked `SKIPPED` so source baselines and seen-item semantics remain safe.

Default behavior is backward-compatible: all event types are enabled.

### Source display priority

`preferences.source_priority` controls only how provenance sources are ordered in Telegram output. It does not change canonical event selection, deduplication, or relevance scoring.

Default:

```yaml
preferences:
  source_priority:
    - vndb
    - steam
    - itch.io
    - rss
```

### Doctor command

```powershell
uv run python -m gal_radar.main doctor --config config.yaml --database data/gal_radar.db
```

The command performs local diagnostics only. It does not call VNDB, Steam, itch.io, RSS feeds, or Telegram.

It reports local database/config state and warns about conditions such as:

- no configured follow targets;
- missing Telegram environment variables;
- all event types disabled.

Warnings do not make the command fail when the configuration and database are otherwise readable.

### Telegram connectivity test

Dry-run:

```powershell
uv run python -m gal_radar.main test-telegram --dry-run
```

Explicit live test:

```powershell
uv run python -m gal_radar.main test-telegram
```

The live form sends exactly one small Traditional Chinese test message and requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

### Verification

`scripts/verify-v1.ps1` now includes both the doctor command and Telegram test dry-run, while continuing to avoid intentional live Telegram delivery.

## Out of scope

Phase 4 does not add:

- Telegram long polling / bot commands;
- Web UI;
- authentication or multi-user support;
- LLM summarization or recommendations;
- Docker/Kubernetes deployment;
- authenticated scraping;
- new content sources.

These remain optional future work rather than requirements for Gal/VN Radar v1.
