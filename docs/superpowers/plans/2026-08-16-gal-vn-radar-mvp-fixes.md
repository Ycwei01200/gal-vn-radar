# Gal/VN Radar MVP Behavior Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stable VNDB developer identity matching, explicit initial baselines and release-state change detection, and optional VNDB cover-image Telegram delivery without changing the MVP architecture.

**Architecture:** VNDB remains the only live source and resolves configured producer names to stable IDs at the adapter boundary. A small snapshot/baseline persistence layer compares current VN state to the previous observation before the existing Pipeline scores and delivers a logical event. `image_url` is an optional field carried through the existing event and SQLite layers; Telegram chooses `sendPhoto` or the existing `sendMessage` path and falls back to text when photo delivery fails.

**Tech Stack:** Python 3.12+, uv, httpx, Pydantic, PyYAML, SQLAlchemy, SQLite, pytest, Ruff.

## Global Constraints

- Keep the existing SourceAdapter, normalizer, Pipeline, EventStore, scoring, Telegram, and zh-TW architecture.
- Do not implement Steam News, other deferred sources, web frameworks, queues, or unrelated refactors.
- Do not call live VNDB or Telegram from automated tests.
- Preserve successful delivery as `SENT`, failed delivery as not `SENT`, dry-run as not `SENT`, and duplicate suppression.
- Keep runtime databases, `.env`, credentials, caches, and temporary configs out of commits.

---

### Task 1: Stable developer IDs and VNDB image fixture shape

**Files:**
- Modify: `src/gal_radar/config.py`
- Modify: `src/gal_radar/models/event.py`
- Modify: `src/gal_radar/adapters/vndb.py`
- Modify: `src/gal_radar/services/normalize.py`
- Test: `tests/test_vndb_adapter.py`
- Test: `tests/test_ranking.py`

**Interfaces:**
- `FollowConfig.resolved_developer_ids: list[str]` is runtime-only and remains empty when no adapter has resolved names.
- `SourceEvent.developer_ids: list[str]` contains all VNDB developer IDs; `developer_id` remains the first ID for compatibility.
- `SourceEvent.image_url: HttpUrl | None` and `NormalizedEvent.image_url: str | None` carry the validated official VNDB image URL.
- `score_event()` uses resolved ID intersection whenever `resolved_developer_ids` is populated and retains display-name matching only for inputs with no resolved IDs.

- [ ] **Step 1: Write failing producer-ID and image fixture tests.**

Use a VNDB fixture with configured `枕`, returned producer `p30`, canonical event developer name `Makura`, and a valid official-looking image URL. Assert `resolved_developer_ids == ["p30"]`, `developer_ids == ["p30"]`, the display name remains `Makura`, and `image_url` survives normalization. Add a ranking test where the event name is `Makura` and only the resolved ID makes it followed.

- [ ] **Step 2: Run the focused tests to verify RED.**

```powershell
$uvExe = (Resolve-Path -LiteralPath '..\work\uv-tool\bin\uv.exe').Path
& $uvExe run pytest tests/test_vndb_adapter.py tests/test_ranking.py -q
```

Expected: failures because runtime producer IDs, all developer IDs, and `image_url` are not implemented.

- [ ] **Step 3: Implement the minimal model and adapter changes.**

Extend the Pydantic models with the optional fields, request `image.url` in the VNDB field list, parse the optional image object, collect all developer IDs, and set `follow.resolved_developer_ids` while resolving each configured producer. Update normalization and scoring to use stable ID intersection before the display-name fallback.

- [ ] **Step 4: Run focused tests and commit.**

```powershell
& $uvExe run pytest tests/test_vndb_adapter.py tests/test_ranking.py -q
git add src/gal_radar/config.py src/gal_radar/models/event.py src/gal_radar/adapters/vndb.py src/gal_radar/services/normalize.py tests/test_vndb_adapter.py tests/test_ranking.py
git commit -m "fix: resolve VNDB developers by stable ID"
```

### Task 2: Snapshot storage and pure change detection

**Files:**
- Create: `src/gal_radar/services/change_detection.py`
- Modify: `src/gal_radar/database.py`
- Create: `tests/test_change_detection.py`
- Test: `tests/test_normalize_and_deduplicate.py`

**Interfaces:**
- `SourceSnapshotState` stores `entity_key`, `title`, `developer_ids`, `release_date`, `release_state`, and `image_url`.
- `detect_change(previous, current, baseline_initialized) -> SourceEvent | None` returns a stable logical event or `None`.
- `EventStore.get_snapshot()`, `save_snapshot()`, `is_baseline_initialized()`, and `mark_baseline_initialized()` manage state.
- `EventStore.initialize()` creates snapshot tables and adds the optional `events.image_url` column only when an existing SQLite schema lacks it.

- [ ] **Step 1: Write failing transition tests.**

Cover first-sync baseline returning `None`, post-baseline unseen VN returning `NEW_TITLE`, TBA/no date to date returning `RELEASE_DATE`, earlier date to later date returning `DELAY` with previous/new metadata, unchanged state returning `None`, and future-to-released returning `RELEASED` only once.

- [ ] **Step 2: Run RED.**

```powershell
& $uvExe run pytest tests/test_change_detection.py -q
```

Expected: collection or assertion failures because the snapshot state and detector do not exist.

- [ ] **Step 3: Implement the pure detector and SQLite state.**

Normalize TBA/empty dates to no date, compare ISO dates, derive stable event IDs such as `v20431:DELAY:2026-09-25->2026-11-27`, create SQLAlchemy snapshot/baseline records, and add a lightweight `ALTER TABLE events ADD COLUMN image_url TEXT` migration guarded by column inspection. Never delete existing rows.

- [ ] **Step 4: Run tests and commit.**

```powershell
& $uvExe run pytest tests/test_change_detection.py tests/test_normalize_and_deduplicate.py -q
git add src/gal_radar/services/change_detection.py src/gal_radar/database.py tests/test_change_detection.py tests/test_normalize_and_deduplicate.py
git commit -m "feat: track VNDB state transitions"
```

### Task 3: Pipeline baseline integration and persistence rules

**Files:**
- Modify: `src/gal_radar/services/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- The pipeline derives a logical change before ranking.
- First source sync stores every current state and never calls the notifier.
- A current snapshot is saved after `SENT`, `SKIPPED`, or `DIGEST`; it remains unchanged after `FAILED` or dry-run `PENDING` so retry remains possible.

- [ ] **Step 1: Write failing sequence-adapter tests.**

Run a future-date VN first, the same state second, and a later-date VN third. Assert first run has no messages and one snapshot, second has no messages, third emits one `DELAY`, and a fourth unchanged run emits none. Add new-title-after-baseline and failed/dry-run retry cases.

- [ ] **Step 2: Run RED.**

```powershell
& $uvExe run pytest tests/test_pipeline.py -q
```

Expected: the current first-run notification assumptions and missing baseline behavior fail.

- [ ] **Step 3: Integrate change detection into `Pipeline.run()`.**

Before `_process_one()`, obtain the snapshot and derive a logical event. On first source run, save the state and skip processing. After a change, process the derived event and save current state only for completed/non-notifying statuses. Mark the baseline only after the adapter run completes.

- [ ] **Step 4: Run and commit.**

```powershell
& $uvExe run pytest tests/test_pipeline.py tests/test_change_detection.py -q
git add src/gal_radar/services/pipeline.py tests/test_pipeline.py
git commit -m "fix: baseline VNDB state before notifying"
```

### Task 4: Cover-image persistence and Telegram sendPhoto fallback

**Files:**
- Modify: `src/gal_radar/database.py`
- Modify: `src/gal_radar/notifications/base.py`
- Modify: `src/gal_radar/notifications/telegram.py`
- Modify: `src/gal_radar/services/pipeline.py`
- Modify: `tests/test_telegram.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- `NotificationSink.send(message: str, *, image_url: str | None = None) -> bool`.
- Valid image URL calls Telegram `sendPhoto` with the existing zh-TW message as caption.
- Missing/invalid image calls `sendMessage`.
- Photo failure retries `sendMessage` on the same client; a second failure raises `TelegramDeliveryError`.

- [ ] **Step 1: Write failing image and persistence tests.**

Use `httpx.MockTransport` to record request paths and payloads. Assert image events call `/sendPhoto`, image-less events call `/sendMessage`, a failed photo followed by successful text returns `True`, two failures raise, both endpoint logs redact the token, dry-run makes zero requests, and `image_url` is persisted and passed by the pipeline.

- [ ] **Step 2: Run RED.**

```powershell
& $uvExe run pytest tests/test_telegram.py tests/test_pipeline.py -q
```

Expected: failures because the notifier accepts text only and EventRecord has no image column.

- [ ] **Step 3: Implement the optional image path.**

Persist validated `image_url`, update the notification protocol and pipeline call, and add `sendPhoto` plus text fallback using the existing token-redacting HTTPX filter. Missing or invalid images remain normal text notifications.

- [ ] **Step 4: Run and commit.**

```powershell
& $uvExe run pytest tests/test_telegram.py tests/test_pipeline.py -q
git add src/gal_radar/database.py src/gal_radar/notifications/base.py src/gal_radar/notifications/telegram.py src/gal_radar/services/pipeline.py tests/test_telegram.py tests/test_pipeline.py
git commit -m "feat: send VNDB cover images to Telegram"
```

### Task 5: Documentation and final verification

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md` only if a current repository rule is needed
- Test: existing fixture tests only when a required transition is still uncovered

- [ ] **Step 1: Update README for actual behavior.**

Document first-run baseline behavior, later state transitions, VNDB ID resolution, cover-image `sendPhoto` with text fallback, SQLite persistence, and unchanged dry-run semantics.

- [ ] **Step 2: Run complete verification.**

```powershell
& $uvExe sync
& $uvExe run pytest
& $uvExe run ruff check .
& $uvExe run python -m gal_radar.main fetch --help
```

Run two isolated fresh-database dry-runs with the existing CLI and confirm baseline storage with zero notifications on both unchanged runs. Do not use the old historical E2E trick.

- [ ] **Step 3: Inspect diff and secrets.**

```powershell
git diff --check
git status --short
git grep -n "TELEGRAM_BOT_TOKEN"
git grep -n "TELEGRAM_CHAT_ID"
```

Do not stage existing untracked E2E configs, runtime databases, caches, or credentials.

- [ ] **Step 4: Commit documentation and finish.**

```powershell
git add README.md AGENTS.md
git commit -m "docs: describe VNDB baselines and image notifications"
```

Run the complete suite again, inspect the full commit range, push `agent/python-mvp`, and verify local HEAD equals `origin/agent/python-mvp`.

