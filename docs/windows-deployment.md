# Windows deployment

Gal/VN Radar v1 is designed to run as CLI commands scheduled by Windows Task Scheduler. No terminal needs to remain open.

## Prerequisites

Install Python 3.12+ and `uv`, clone the repository, then run `uv sync`. Copy `config.example.yaml` to local `config.yaml` and keep it untracked.

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the Windows account/environment used by Task Scheduler. Do not put secrets in YAML, scripts, or task XML.

## Manual verification

From the repository root:

```powershell
uv run python -m gal_radar.main fetch --dry-run --config config.yaml --database data/gal_radar.db
uv run python -m gal_radar.main status --config config.yaml --database data/gal_radar.db
uv run python -m gal_radar.main digest --dry-run --config config.yaml --database data/gal_radar.db
uv run python -m gal_radar.main backup --database data/gal_radar.db --output backups
```

The first successful fetch for a new feed establishes the existing silent baseline. A second unchanged fetch should not produce historical notifications.

## Task Scheduler

Create two tasks. Use `powershell.exe` as Program/script.

Fetch task arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "<REPO>\scripts\run-fetch.ps1"
```

Recommended trigger: every 30 minutes.

Digest task arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "<REPO>\scripts\run-digest.ps1"
```

Recommended trigger: daily at 20:00 local time.

Set **Start in** to the repository root. Configure retry on failure (for example restart every 5 minutes, up to 3 attempts). `Run whether user is logged on or not` is suitable only if that account can access the repo, `uv`, network, and Telegram environment variables.

## Exit codes

- `0`: successful command, including no-new-event and empty-digest runs.
- `1`: unrecoverable config/database/runtime failure, or all configured top-level adapters failed.
- isolated source failures remain logged while healthy adapters continue.

## Logs

Console logging remains enabled. A rotating log is written to `logs/gal-radar.log` by default. Rotation is 5 MiB per file with 5 backups. Set `GAL_RADAR_LOG_PATH` to override the path.

## Backup

`scripts/backup-db.ps1` uses the SQLite backup API through the CLI and creates a timestamped file under `backups/`. There is no automatic retention in v1; prune old `gal-radar-*.db` files manually or with a separate scheduled policy.

## Restore

1. Disable fetch/digest scheduled tasks.
2. Preserve the current DB by renaming or copying it.
3. Copy the chosen backup to the configured DB path.
4. Run `status`.
5. Run a manual `fetch --dry-run`.
6. Re-enable scheduled tasks.

The application never automatically overwrites the live database during restore.

## Troubleshooting

Check Task Scheduler History, the task's Last Run Result, and `logs/gal-radar.log`. Confirm the scheduled account sees the same `uv` executable and Telegram environment variables as the interactive shell. `status` never calls external source APIs or sends Telegram messages.
