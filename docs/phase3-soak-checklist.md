# Phase 3 soak checklist

## Day 0

- Run `status`; database reports `ok`.
- Run first fetch and confirm new feeds establish a silent baseline.
- Run a second unchanged fetch and confirm no historical spam.
- Create a database backup.
- Confirm `logs/gal-radar.log` is written.

## Repeated polling

Run `scripts/soak-test.ps1 -Iterations 10 -IntervalSeconds 60` (use `-DryRun` when Telegram delivery is not intended).

Verify:
- no duplicate notifications;
- seen-item counts remain stable for unchanged feeds;
- source failures are isolated and logged;
- fatal CLI failures stop the soak script.

## Restart persistence

Close the process, start a new shell/process, and fetch the same unchanged sources again. Existing snapshot baselines and feed `source_seen_items` must prevent replay. A later new item should process exactly once.

## Failure recovery

Temporarily use a known-invalid test feed/config only in a local test config. Confirm healthy sources continue. Restore the valid config and confirm the failed source can be retried.

## Digest

Confirm pending DIGEST events are sent once. For automated tests, partial batch failure must leave only the failed/later batch in DIGEST state.

## Long-running claim

Do not claim production stability until a real multi-hour/day soak has actually been observed. Record start/end time, number of fetch cycles, source failures, duplicate count, and Telegram delivery issues.
