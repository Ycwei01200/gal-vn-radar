# Windows deployment

Gal/VN Radar v1 is designed to run as CLI commands scheduled by Windows Task Scheduler. No terminal needs to remain open.

## Prerequisites

Install Python 3.12+ and `uv`, clone the repository, then run `uv sync`. Copy `config.example.yaml` to local `config.yaml` and keep it untracked.

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the Windows user environment used by Task Scheduler. Do not put secrets in YAML, scripts, or task XML.

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

The preferred setup is the repository installer:

```powershell
.\scripts\install-scheduled-tasks.ps1
```

It creates:

- `GalVNRadar-Fetch`: starts about one minute after registration and repeats every 30 minutes.
- `GalVNRadar-Digest`: runs every day at 20:00 local time.

Both tasks use these operational settings:

- start when available after a missed trigger;
- retry after 5 minutes on failure;
- retry up to 3 times;
- 15-minute execution limit;
- ignore a new trigger while the previous instance is still running.

To replace existing tasks intentionally:

```powershell
.\scripts\install-scheduled-tasks.ps1 -Force
```

Check the registered tasks with:

```powershell
.\scripts\check-scheduled-tasks.ps1
```

The default registration uses the current user's interactive token. This is the safest no-password setup and works while the user is logged in. To run while logged out, open Task Scheduler, edit each task, choose **Run whether user is logged on or not**, and provide the Windows account password when requested. Confirm that account can access the repository, `uv`, the network, and the Telegram user environment variables.

The runner scripts resolve the repository from their own location, locate `uv`, and re-read `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` from the current user's persistent environment if the scheduled PowerShell process did not inherit them.

### Manual equivalent

If tasks are created through the GUI instead, use `powershell.exe` as Program/script.

Fetch arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "<REPO>\scripts\run-fetch.ps1"
```

Digest arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "<REPO>\scripts\run-digest.ps1"
```

Set **Start in** to the repository root.

## Exit codes

- `0`: successful command, including no-new-event and empty-digest runs.
- `1`: unrecoverable config/database/runtime failure, or all configured top-level adapters failed.
- isolated source failures remain logged while healthy adapters continue.

## Logs

Console logging remains enabled. A rotating log is written to `logs/gal-radar.log` by default. Rotation is 5 MiB per file with 5 backups. Set `GAL_RADAR_LOG_PATH` to override the path.

## Backup

`scripts/backup-db.ps1` uses the SQLite backup API through the CLI and creates a timestamped file under `backups/`. There is no automatic retention in v1; prune old `gal-radar-*.db` files manually or with a separate scheduled policy.

## Short soak validation

A practical v1 validation is 10 fetch cycles at one-minute intervals:

```powershell
.\scripts\soak-test.ps1 -Iterations 10 -IntervalSeconds 60 -DryRun
```

Pass criteria:

- all 10 CLI invocations exit successfully;
- no duplicate historical events are created;
- the process can be restarted between runs without replaying established state;
- `logs/gal-radar.log` continues to receive entries;
- `status` remains healthy after the run;
- a separate `digest --dry-run` succeeds;
- if a source failure is deliberately simulated, healthy sources continue and the failed source remains retryable.

A multi-hour/day soak increases production confidence but is not required for the v1 functional completion claim.

## Restore

1. Disable fetch/digest scheduled tasks.
2. Preserve the current DB by renaming or copying it.
3. Copy the chosen backup to the configured DB path.
4. Run `status`.
5. Run a manual `fetch --dry-run`.
6. Re-enable scheduled tasks.

The application never automatically overwrites the live database during restore.

## Troubleshooting

Check Task Scheduler History, the task's Last Run Result, `scripts/check-scheduled-tasks.ps1`, and `logs/gal-radar.log`. Confirm the scheduled account sees the same `uv` executable and Telegram environment variables as the interactive shell. `status` never calls external source APIs or sends Telegram messages.
