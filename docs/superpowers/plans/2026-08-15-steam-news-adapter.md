# SteamNewsAdapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tested Steam news source adapter that maps public Steam app IDs to VN entities, normalizes announcements into domain events, deduplicates them across sources before notification, and preserves `zh-TW` notification formatting.

**Architecture:** Keep a small TypeScript ports-and-adapters core. `SteamNewsAdapter` owns Steam HTTP DTO parsing and returns domain `Event` values; `EventIngestService` owns repository acceptance and cross-source deduplication; `NotificationService` owns locale-specific formatting and delegates delivery to a notification sink. The adapter has no notification dependency.

**Tech Stack:** Node.js 20+, TypeScript 5.x, Vitest, native `fetch`, npm.

## Global Constraints

- Steam app IDs are global public identifiers and the mapping is not tied to a Steam account.
- The adapter must implement `SourceAdapter` and must not import or call notification code.
- Steam requests use `https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/` with bounded `count` and `maxlength` query values.
- Live Steam HTTP is forbidden in tests; all adapter tests use JSON fixtures and an injected fetch function.
- Unmapped apps, malformed payloads, and HTTP failures must not become fake domain events.
- Cross-source deduplication occurs in `EventIngestService`, before repository insertion and notification.
- `zh-TW` output is formatted by `NotificationService`, not by `SteamNewsAdapter`.
- Run `npm test` and `npm run typecheck` before claiming completion.
- Do not push until the local diff and verification results have been shown for approval.

---

## File map

Create these focused files:

```text
package.json
tsconfig.json
src/
  application/
    event-ingest-service.ts
    ports/event-notifier.ts
    ports/event-repository.ts
    ports/source-adapter.ts
  config/
    steam-app-mappings.ts
    vn-entities.ts
  domain/
    event.ts
    vn.ts
  infrastructure/
    memory/in-memory-event-repository.ts
    notifications/notification-service.ts
    steam/steam-news-adapter.ts
    steam/steam-news-types.ts
  index.ts
tests/
  fixtures/steam-news/clannad.json
  fixtures/steam-news/fata-morgana.json
  event-ingest.test.ts
  event-identity.test.ts
  steam-news-adapter.test.ts
```

The public API in `src/index.ts` exports the domain types, ports, adapter,
ingestion service, in-memory repository, and notification service. No scheduler
or UI is added in this vertical slice.

---

### Task 1: Project setup and domain/source contracts

**Files:**

- Create: `package.json`
- Create: `tsconfig.json`
- Create: `src/domain/vn.ts`
- Create: `src/domain/event.ts`
- Create: `src/application/ports/source-adapter.ts`
- Create: `src/application/ports/event-repository.ts`
- Create: `src/application/ports/event-notifier.ts`
- Create: `tests/event-identity.test.ts`

**Interfaces:**

```typescript
// src/domain/vn.ts
export interface VNEntity {
  readonly id: string;
  readonly name: string;
}

// src/domain/event.ts
export type EventKind = "news";

export interface Event {
  readonly vnId: string;
  readonly kind: EventKind;
  readonly source: string;
  readonly sourceEventId: string;
  readonly title: string;
  readonly summary: string | null;
  readonly url: string;
  readonly publishedAt: string;
  readonly metadata: Readonly<Record<string, string>>;
}

export function eventKeys(event: Event): readonly string[];

// src/application/ports/source-adapter.ts
export interface SourceAdapter {
  readonly source: string;
  fetchEvents(): Promise<readonly Event[]>;
}

// src/application/ports/event-repository.ts
export interface EventRepository {
  hasEquivalent(event: Event): Promise<boolean>;
  add(event: Event): Promise<void>;
  list(): Promise<readonly Event[]>;
}

// src/application/ports/event-notifier.ts
import type { Event } from "../../domain/event.js";
import type { VNEntity } from "../../domain/vn.js";

export interface EventNotifier {
  notify(event: Event, vn: VNEntity): Promise<void>;
}
```

- [ ] **Step 1: Add npm and TypeScript configuration**

Create `package.json` with `type: "module"` and these scripts:

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit"
  }
}
```

Install the test/build tools with `npm install --save-dev typescript vitest`.
Use `tsconfig.json` with `target: "ES2022"`, `module: "NodeNext"`,
`moduleResolution: "NodeNext"`, `strict: true`, `noEmit: true`,
`esModuleInterop: true`, and `skipLibCheck: true`.

- [ ] **Step 2: Write the failing event identity tests**

In `tests/event-identity.test.ts`, add tests for these exact behaviors:

```typescript
const event = (url: string): Event => ({
  vnId: "vn-clannad",
  kind: "news",
  source: "steam",
  sourceEventId: "gid-42",
  title: " Major   Update! ",
  summary: "details",
  url,
  publishedAt: "2026-08-15T12:00:00.000Z",
  metadata: {},
});

it("uses canonical URL as the strongest cross-source key", () => {
  expect(eventKeys(event("https://steamcommunity.com/news/42"))[0])
    .toBe("vn-clannad|news|url|https://steamcommunity.com/news/42");
});

it("falls back to normalized title and UTC publication day", () => {
  expect(eventKeys(event(""))[0])
    .toBe("vn-clannad|news|title|major update|day|2026-08-15");
});

it("keeps source identity as a same-source duplicate guard", () => {
  expect(eventKeys(event(""))[1])
    .toBe("vn-clannad|news|source|steam|gid-42");
});
```

The helper should create a complete `Event`; the test must exercise the real
normalization function rather than duplicate its implementation.

- [ ] **Step 3: Run the focused test and verify the expected red failure**

Run `npm test -- tests/event-identity.test.ts`.

Expected result: Vitest reports the missing `eventKeys` export or equivalent
feature-missing failure. Fix test typos if the failure is a module-resolution
error; do not add production code before the behavior fails correctly.

- [ ] **Step 4: Implement the minimal domain contracts**

Implement `eventKeys` with these rules:

1. normalize URL by trimming, lowercasing the host, and removing a trailing
   `/`; emit a URL key only when the URL is non-empty;
2. normalize title by trimming, lowercasing, collapsing whitespace, and
   removing punctuation runs;
3. use the UTC `YYYY-MM-DD` portion of `publishedAt`;
4. return the URL key first when present, followed by the title-day key and
   source-identity key; never return an empty URL key.

Implement the four interfaces exactly as shown above. Keep them free of Steam
DTOs and notification-provider details.

- [ ] **Step 5: Run focused tests, typecheck, and commit**

Run:

```powershell
npm test -- tests/event-identity.test.ts
npm run typecheck
```

Expected result: all identity tests pass and typecheck exits 0. Commit with
`feat: add domain and source adapter contracts`.

---

### Task 2: Steam app mapping and SteamNewsAdapter

**Files:**

- Create: `src/config/vn-entities.ts`
- Create: `src/config/steam-app-mappings.ts`
- Create: `src/infrastructure/steam/steam-news-types.ts`
- Create: `src/infrastructure/steam/steam-news-adapter.ts`
- Create: `tests/fixtures/steam-news/clannad.json`
- Create: `tests/fixtures/steam-news/fata-morgana.json`
- Create: `tests/steam-news-adapter.test.ts`

**Interfaces:**

```typescript
// src/config/steam-app-mappings.ts
export interface SteamAppMapping {
  readonly appId: number;
  readonly vnId: string;
}

export const STEAM_APP_MAPPINGS: readonly SteamAppMapping[];

// src/infrastructure/steam/steam-news-adapter.ts
export interface SteamNewsAdapterOptions {
  readonly count?: number;
  readonly maxLength?: number;
  readonly fetchImpl?: typeof fetch;
}

export class SteamNewsAdapter implements SourceAdapter {
  readonly source = "steam";
  constructor(
    mappings: readonly SteamAppMapping[],
    options?: SteamNewsAdapterOptions,
  );
  fetchEvents(): Promise<readonly Event[]>;
}
```

- [ ] **Step 1: Add fixture files and write failing adapter tests**

Each fixture must contain the real Steam shape:

```json
{
  "appnews": {
    "appid": 324160,
    "newsitems": [
      {
        "gid": "steam-gid-1",
        "title": "Major Update",
        "url": "https://steamcommunity.com/news/steam-gid-1",
        "date": 1786752000,
        "contents": "Update details",
        "feedname": "steam_community_announcements"
      }
    ]
  }
}
```

Use a second fixture with app ID `303310` and a different news item. Tests must
assert:

- app `324160` maps to `vn-clannad` and app `303310` maps to
  `vn-fata-morgana`;
- the fake fetch sees exactly one URL per mapped app with `count=20`,
  `maxlength=300`, and the requested app ID;
- the adapter returns `kind: "news"`, `source: "steam"`, Steam `gid`, title,
  summary, original URL, ISO publication time, and app ID metadata;
- only mapped app IDs are requested; an app ID without a mapping makes no
  request and produces no event;
- duplicate fixture items with the same `gid` produce one event;
- non-OK responses and malformed `appnews.newsitems` reject with an error that
  includes the app ID;
- no notifier or notification import is involved in the adapter test.

- [ ] **Step 2: Run adapter tests to verify the expected red failure**

Run `npm test -- tests/steam-news-adapter.test.ts`.

Expected result: failure because `SteamNewsAdapter` and the mapping exports do
not yet exist. Correct only test setup errors before implementation.

- [ ] **Step 3: Implement the mapping and Steam DTO parser**

Create `VN_ENTITIES` with:

```typescript
export const VN_ENTITIES = {
  clannad: { id: "vn-clannad", name: "CLANNAD" },
  fataMorgana: { id: "vn-fata-morgana", name: "The House in Fata Morgana" },
} as const satisfies Record<string, VNEntity>;
```

Create `STEAM_APP_MAPPINGS` for app IDs `324160 -> vn-clannad` and
`303310 -> vn-fata-morgana`. Keep the mapping as plain data; it must not read
Steam credentials or user settings.

Define internal DTO types for `appnews`, `newsitems`, `gid`, `title`, `url`,
`date`, and `contents`. Validate the runtime shape before accessing fields.

- [ ] **Step 4: Implement the minimal adapter**

For each mapping, request:

```text
https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=<appId>&count=20&maxlength=300&format=json
```

Use an injected `fetchImpl` defaulting to global `fetch`. Reject non-OK
responses and malformed payloads. Normalize `date` from Unix seconds to ISO,
trim title and contents, preserve the original URL, set `sourceEventId` to
`gid`, and include `{ appId: String(appId) }` in metadata. De-duplicate repeated
items by `eventKeys` before returning.

- [ ] **Step 5: Run focused tests, typecheck, and commit**

Run:

```powershell
npm test -- tests/steam-news-adapter.test.ts
npm run typecheck
```

Expected result: all adapter fixture tests pass and typecheck exits 0. Commit
with `feat: add Steam news source adapter`.

---

### Task 3: Ingestion deduplication and zh-TW notifications

**Files:**

- Create: `src/application/event-ingest-service.ts`
- Create: `src/infrastructure/memory/in-memory-event-repository.ts`
- Create: `src/infrastructure/notifications/notification-service.ts`
- Create: `tests/event-ingest.test.ts`

**Interfaces:**

```typescript
// src/application/event-ingest-service.ts
export class EventIngestService {
  constructor(
    repository: EventRepository,
    notifier: EventNotifier,
    vnEntities: readonly VNEntity[],
  );
  ingest(events: readonly Event[]): Promise<readonly Event[]>;
}

// src/infrastructure/notifications/notification-service.ts
export interface NotificationMessage {
  readonly locale: "zh-TW";
  readonly title: string;
  readonly body: string;
  readonly url: string;
}

export interface NotificationSink {
  send(message: NotificationMessage): Promise<void>;
}

export class NotificationService implements EventNotifier {
  constructor(sink: NotificationSink);
  notify(event: Event, vn: VNEntity): Promise<void>;
}
```

- [ ] **Step 1: Write failing ingestion and notification tests**

Add tests for these exact cases:

```typescript
it("stores and notifies a new Steam event once", async () => {
  const accepted = await service.ingest([steamEvent]);
  expect(accepted).toEqual([steamEvent]);
  expect(await repository.list()).toEqual([steamEvent]);
  expect(sink.messages).toHaveLength(1);
});

it("does not insert or notify an equivalent event from another source", async () => {
  await repository.add(existingOtherSourceEvent);
  const accepted = await service.ingest([steamEventWithSameUrl]);
  expect(accepted).toEqual([]);
  expect(sink.messages).toEqual([]);
});

it("formats accepted notifications in zh-TW", async () => {
  await service.ingest([steamEvent]);
  expect(sink.messages[0]).toMatchObject({
    locale: "zh-TW",
    title: "【CLANNAD】Major Update",
    url: steamEvent.url,
  });
});
```

Also test title-and-UTC-day fallback dedup when two sources use different URLs,
and confirm a missing VN entity fails before insertion or notification.

- [ ] **Step 2: Run ingestion tests to verify the expected red failure**

Run `npm test -- tests/event-ingest.test.ts` and confirm the failure is caused
by the missing ingestion/repository/notification implementation.

- [ ] **Step 3: Implement the in-memory repository and ingestion service**

`InMemoryEventRepository.hasEquivalent` must compare every key from
`eventKeys(event)` against every stored event's keys. `add` must preserve event
order. `EventIngestService.ingest` must:

1. resolve the event's VN entity;
2. skip it if `hasEquivalent` is true;
3. add it;
4. call `notifier.notify` only after a successful add;
5. return only accepted events in input order.

If the VN ID is unknown, throw an error before mutating the repository.

- [ ] **Step 4: Implement the zh-TW notification service**

Format exactly:

```text
title: 【<VN name>】<event title>
body: <summary or empty string>
       <event url>
locale: zh-TW
```

Pass the resulting `NotificationMessage` to the injected sink. Do not perform
network delivery in `NotificationService`; the sink is the provider boundary.

- [ ] **Step 5: Run focused tests, typecheck, and commit**

Run:

```powershell
npm test -- tests/event-ingest.test.ts
npm run typecheck
```

Expected result: all dedup and `zh-TW` tests pass. Commit with
`feat: add event ingestion and zh-TW notifications`.

---

### Task 4: Public exports, full verification, and review handoff

**Files:**

- Create: `src/index.ts`
- Modify: `README.md`
- Test: all files under `tests/`

- [ ] **Step 1: Export the supported public API**

`src/index.ts` must export the domain types/functions, ports, config mappings,
`SteamNewsAdapter`, `EventIngestService`, `InMemoryEventRepository`, and
`NotificationService`. It must not export Steam response DTOs as domain types.

- [ ] **Step 2: Add a README usage example**

Document that app-ID mappings are public global data, show constructing the
adapter with an injected fetch, and state that ingestion—not the adapter—owns
deduplication and notification. Do not document Steam credentials.

- [ ] **Step 3: Run the complete local verification**

Run exactly:

```powershell
npm test
npm run typecheck
git diff --check
git status --short --branch
```

Expected result: the full Vitest suite passes, typecheck exits 0, diff check is
clean, and the status output lists only intended implementation files.

- [ ] **Step 4: Rebuild the code-review graph and run final review**

Run the graph incremental update from the repository root, confirm its head SHA
matches the current commit, inspect changed symbols/callers/callees/tests, and
run the delegated final review against the complete branch diff. Resolve every
material finding before completion.

- [ ] **Step 5: Show the final diff and wait for push approval**

Report the commit list, changed files, test output, graph status, and repository
URL. Do not push until the user explicitly approves the validated local diff.
