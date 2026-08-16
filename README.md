# gal-vn-radar

Gal/VN Radar tracks visual-novel release and news events through source
adapters.

## Steam news

Steam app IDs are public global identifiers, mapped to the radar's existing VN
IDs. They are not tied to a Steam user account or credentials:

| Steam app ID | VN entity |
| --- | --- |
| `324160` | `vn-clannad` — CLANNAD |
| `303310` | `vn-fata-morgana` — The House in Fata Morgana |

The adapter accepts an injected `fetch` implementation, which keeps tests
fixture-based and avoids requiring Steam credentials:

```ts
import {
  EventIngestService,
  InMemoryEventRepository,
  NotificationService,
  type NotificationSink,
  STEAM_APP_MAPPINGS,
  SteamNewsAdapter,
  VN_ENTITIES,
} from "gal-vn-radar";

declare const notificationSink: NotificationSink;

const adapter = new SteamNewsAdapter(STEAM_APP_MAPPINGS, {
  fetchImpl: fetch,
});
const events = await adapter.fetchEvents();

const repository = new InMemoryEventRepository();
const notifier = new NotificationService(notificationSink);
const ingestion = new EventIngestService(
  repository,
  notifier,
  Object.values(VN_ENTITIES),
);

await ingestion.ingest(events);
```

The adapter only fetches and normalizes Steam announcements into `Event`
objects. Ingestion owns cross-source deduplication before persistence and
notification. Notifications retain the existing `zh-TW` locale behavior.
