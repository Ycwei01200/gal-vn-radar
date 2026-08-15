# SteamNewsAdapter design

Date: 2026-08-15
Repository: `Ycwei01200/gal-vn-radar`
Status: proposed for written-spec review

## Context and scope

The requested Gal/VN Radar source repository was not available locally, so a
new public repository was created. The repository currently contains only its
README; there is no existing domain model, adapter interface, notification
service, or test suite to preserve. This design therefore introduces the
smallest architecture needed to satisfy the requested behavior and keeps the
Steam integration behind a source port.

In scope:

- map global Steam app IDs to stable internal VN entity IDs;
- fetch Steam announcements through the public `GetNewsForApp` endpoint;
- normalize Steam news into the domain `Event` model;
- deduplicate equivalent events across sources before notification;
- keep notification delivery outside the adapter;
- preserve a `zh-TW` notification formatter;
- cover the adapter and ingestion path with JSON fixture tests.

Out of scope:

- Steam account login, user-owned libraries, or per-user Steam credentials;
- crawling Steam store pages or community content outside announcements;
- a UI, persistence database, scheduler, or notification provider integration.

The app-ID mapping is global repository data. Per-user tracking or subscription
preferences, if added later, must be modeled separately from the mapping.

## Approaches considered

### A. Minimal TypeScript ports-and-adapters design (recommended)

Use a small TypeScript domain/application core, an injected `fetch` function for
Steam, and a notification port consumed by the application layer. Use Vitest
for unit and fixture tests.

Advantages: explicit contracts, easy HTTP fakes, no framework lock-in, and a
clear boundary for future sources. The implementation stays small enough for a
new repository.

### B. Plain JavaScript modules

This would reduce compilation setup, but it would make the mapping and normalized
event contracts runtime-only. It is less suitable for a source adapter whose
external payload is structurally different from the domain model.

### C. Full application framework

NestJS or a similar framework would provide dependency injection and module
conventions, but it would add configuration and runtime surface unrelated to
the requested adapter. It is deferred until the repository has application
features that justify it.

## Architecture

The dependency direction is:

`SteamNewsAdapter -> SourceAdapter port -> EventIngestService -> EventRepository`

`EventIngestService -> NotificationPort`

The adapter never receives or calls a notifier. It returns normalized events;
the ingestion service decides whether an event is new and the notification
port is called only for accepted events.

### Domain types

`VNEntity` contains a stable internal `id` and display metadata. A
`SteamAppMapping` contains a numeric `appId` and the target `vnId`. Steam app
IDs are global public identifiers and are not tied to a Steam account.

`Event` contains:

- `vnId`;
- `kind` (`news` for this adapter);
- `source` and `sourceEventId`;
- title, optional summary, canonical URL, and ISO publication time;
- optional source metadata needed for traceability.

The normalized event keeps the original Steam URL and `gid` so source-specific
identity remains available without leaking Steam DTOs into the domain.

### SourceAdapter port

The port accepts a list of mapped source targets and returns normalized events.
The concrete adapter receives an injected `fetch` implementation and a mapping
collection. Its responsibilities are limited to request construction, response
shape validation, mapping, and normalization.

The adapter will:

1. ignore Steam app IDs that have no configured VN mapping;
2. request `GetNewsForApp` for each mapped app;
3. reject non-success HTTP responses and malformed payloads with a source-
   specific error;
4. normalize each news item into an `Event` without sending notifications.

The production request uses a bounded item count and maximum content length.
Tests provide a fake fetch implementation and never call Steam.

### Cross-source deduplication

Deduplication belongs to `EventIngestService`, not `SteamNewsAdapter`, so the
same rule applies when a future source is added. The service compares a new
event with existing events for the same VN and kind in this order:

1. canonical URL, when present;
2. normalized title plus publication calendar day, when the URL differs or is
   absent;
3. source identity (`source` + `sourceEventId`) as a final same-source guard.

When an equivalent event already exists, ingestion skips insertion and
notification. A source reference may be retained by the repository later, but
the initial implementation will not duplicate the event object merely because
the source changed.

### Notification and `zh-TW`

`EventIngestService` depends on a `NotificationPort`; it does not know how a
provider delivers messages. `NotificationService` formats accepted events by
locale. The initial formatter preserves `zh-TW` output for the event title,
summary, VN name, and link. The adapter passes through source text and does not
translate or format notifications.

## Error handling

- Unmapped app IDs are ignored and do not produce domain events.
- HTTP failures and invalid Steam payloads are reported as adapter errors with
  the app ID; they are not converted into fake events.
- Empty news lists are valid and produce no events.
- Duplicate items within one Steam response are removed by the same normalized
  identity before returning from the adapter.
- Notifications happen only after repository acceptance, so a source fetch
  cannot notify on an event that was rejected as a duplicate.

## Test design

Fixture files will model the Steam response shape and remain independent of the
live Steam API. Tests will cover:

1. app-ID mapping to the intended VN entity;
2. request URL construction and normalization of title, summary, URL, date,
   `gid`, and source metadata;
3. unmapped apps, empty responses, malformed payloads, and HTTP failures;
4. duplicate Steam items and cross-source equivalent events;
5. the adapter's lack of notification side effects;
6. `zh-TW` notification formatting after ingestion;
7. the full `npm test` suite and TypeScript typecheck.

## Initial project layout

```text
src/
  domain/
    event.ts
    vn.ts
  application/
    ports/source-adapter.ts
    ports/event-repository.ts
    ports/notification.ts
    event-ingest-service.ts
  infrastructure/
    steam/steam-news-adapter.ts
    notifications/notification-service.ts
  config/steam-app-mappings.ts
tests/
  fixtures/steam-news/*.json
  steam-news-adapter.test.ts
  event-ingest.test.ts
```

The repository will use TypeScript, Vitest, and the platform `fetch` API. No
database or framework is required for the first vertical slice; an in-memory
repository and notification spy are sufficient for tests.

## Acceptance criteria

- `SteamNewsAdapter` implements the source port and has no notification
  dependency.
- Mapped Steam announcements become valid domain events with stable source
  identity and URLs.
- Equivalent events from another source are not inserted or notified twice.
- `zh-TW` notification output remains handled by the notification layer.
- Fixture-based focused tests and the complete repository test suite pass.
- The implementation is locally validated before any push to GitHub.
