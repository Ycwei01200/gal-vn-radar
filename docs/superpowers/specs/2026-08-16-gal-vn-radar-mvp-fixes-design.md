# Gal/VN Radar MVP Behavior Fixes Design

**Date:** 2026-08-16

**Goal:** Fix stable VNDB developer matching, prevent historical initial-sync notifications while detecting later release transitions, and add reliable optional VN cover images to Telegram notifications.

## Constraints

- Keep Python 3.12+, uv, httpx, Pydantic, PyYAML, SQLAlchemy, SQLite, pytest, and Ruff.
- Preserve the existing SourceAdapter, normalizer, pipeline, EventStore, deterministic scoring, Telegram, and zh-TW architecture.
- Do not implement Steam, other deferred sources, new web frameworks, queues, or broad refactors.
- Automated tests use fixtures and mocks only; no live VNDB or Telegram calls.

## Design

### Developer identity

`FollowConfig` keeps human-readable developer names and gains a runtime-only list of resolved VNDB producer IDs. `VNDBAdapter` resolves each configured name through `/producer`, records the IDs on the follow object, and exposes every VNDB developer ID on `SourceEvent` in addition to display names. The scorer uses ID intersection whenever resolved IDs are available and retains display-name matching only for source/test inputs that have no resolved IDs. No alias table is added.

The IDs and names flow through `NormalizedEvent` and `EventRecord` so notifications can continue showing original names while scoring uses stable identity.

### Initial baseline and change detection

Add two small SQLite tables:

- `source_snapshots`: one current state per `(source, entity_key)`, including VN ID, title, developer IDs, release date/state, image URL, and observation time.
- `source_baselines`: one marker per source indicating that its first complete observation has finished.

The adapter continues to fetch current VNDB state. A pure change detector compares that state with the stored snapshot:

- no snapshot before the source baseline: save baseline only;
- no snapshot after the source baseline: emit `NEW_TITLE`;
- TBA/no date to a date: `RELEASE_DATE`;
- a later date: `DELAY` with previous and updated dates in metadata;
- a transition from unreleased to released at the same known date: `RELEASED`;
- unchanged state: no event.

The pipeline saves the new snapshot after a change is successfully handled, skipped, or digested. It retains the previous snapshot for failed or dry-run pending delivery so the existing retry path can process the same logical event later. Event IDs are derived from the stable VN ID and transition values, not from the polling timestamp.

`EventStore.initialize()` creates the new tables and adds the optional `events.image_url` column with a small SQLite `ALTER TABLE` migration when an existing database lacks it. No Alembic dependency is introduced.

### Cover images and Telegram

The VNDB query requests the official image URL and validates it as an optional HTTP(S) URL in `SourceEvent`. `image_url` is propagated through normalization and persistence. The notifier interface accepts an optional image URL:

- valid image URL: call `sendPhoto` with the existing zh-TW message as caption;
- missing or invalid image: call `sendMessage`;
- photo delivery failure: retry the same message with `sendMessage` using the same client;
- if both fail, raise the existing delivery error so the pipeline does not mark the event `SENT`.

The existing HTTPX logger filter redacts the bot token for both endpoint paths without changing logger levels. Dry-run returns before any Telegram request and keeps the event non-`SENT`.

## Testing

Fixture tests will cover producer ID resolution and canonical-name mismatch, all baseline/change transitions, snapshot retry behavior, image propagation/persistence, sendPhoto/text fallback/photo failure, token redaction for both endpoints, dry-run, existing failure/dedup semantics, and zh-TW terminology. A fresh isolated SQLite CLI dry-run will verify that the first sync stores baseline state without notifications and the second unchanged sync stays quiet.

## Scope Decision

The implementation intentionally does not add a subscription database, event sourcing, image downloading/cache, live service tests, or any deferred source integration.
