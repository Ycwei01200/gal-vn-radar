import { describe, expect, it } from "vitest";

import { EventIngestService } from "../src/application/event-ingest-service.js";
import { VN_ENTITIES } from "../src/config/vn-entities.js";
import type { Event } from "../src/domain/event.js";
import { InMemoryEventRepository } from "../src/infrastructure/memory/in-memory-event-repository.js";
import {
  NotificationService,
  type NotificationMessage,
} from "../src/infrastructure/notifications/notification-service.js";

class CollectingSink {
  readonly messages: NotificationMessage[] = [];

  async send(message: NotificationMessage): Promise<void> {
    this.messages.push(message);
  }
}

const steamEvent: Event = {
  vnId: VN_ENTITIES.clannad.id,
  kind: "news",
  source: "steam",
  sourceEventId: "steam-gid-1",
  title: "Major Update",
  summary: "Update details",
  url: "https://steamcommunity.com/news/steam-gid-1",
  publishedAt: "2026-08-15T12:00:00.000Z",
  metadata: { appId: "324160" },
};

describe("EventIngestService", () => {
  it("stores and notifies a new Steam event once", async () => {
    const { repository, service, sink } = createSubject();

    const accepted = await service.ingest([steamEvent]);

    expect(accepted).toEqual([steamEvent]);
    expect(await repository.list()).toEqual([steamEvent]);
    expect(sink.messages).toHaveLength(1);
  });

  it("does not insert or notify an equivalent event from another source", async () => {
    const { repository, service, sink } = createSubject();
    const existingOtherSourceEvent: Event = {
      ...steamEvent,
      source: "rss",
      sourceEventId: "rss-item-1",
    };
    const steamEventWithSameUrl: Event = {
      ...steamEvent,
      sourceEventId: "steam-gid-2",
    };

    await repository.add(existingOtherSourceEvent);

    const accepted = await service.ingest([steamEventWithSameUrl]);

    expect(accepted).toEqual([]);
    expect(await repository.list()).toEqual([existingOtherSourceEvent]);
    expect(sink.messages).toEqual([]);
  });

  it("formats accepted notifications in zh-TW", async () => {
    const { service, sink } = createSubject();

    await service.ingest([steamEvent]);

    expect(sink.messages[0]).toMatchObject({
      locale: "zh-TW",
      title: "【CLANNAD】Major Update",
      body: `Update details\n${steamEvent.url}`,
      url: steamEvent.url,
    });
  });

  it("falls back to title and UTC day when equivalent events use different URLs", async () => {
    const { repository, service, sink } = createSubject();
    const existingOtherSourceEvent: Event = {
      ...steamEvent,
      source: "rss",
      sourceEventId: "rss-item-2",
      url: "https://example.com/clannad-major-update",
      title: " Major   Update! ",
    };
    const steamEventWithDifferentUrl: Event = {
      ...steamEvent,
      sourceEventId: "steam-gid-3",
      url: "https://steamcommunity.com/games/324160/announcements/detail/999",
      title: "major update",
      publishedAt: "2026-08-15T23:59:59.000Z",
    };

    await repository.add(existingOtherSourceEvent);

    const accepted = await service.ingest([steamEventWithDifferentUrl]);

    expect(accepted).toEqual([]);
    expect(await repository.list()).toEqual([existingOtherSourceEvent]);
    expect(sink.messages).toEqual([]);
  });

  it("fails unknown VN entities before insertion or notification", async () => {
    const { repository, service, sink } = createSubject();
    const unknownEvent: Event = {
      ...steamEvent,
      vnId: "vn-missing",
    };

    await expect(service.ingest([unknownEvent])).rejects.toThrow(/vn-missing/);
    expect(await repository.list()).toEqual([]);
    expect(sink.messages).toEqual([]);
  });
});

function createSubject(): {
  repository: InMemoryEventRepository;
  service: EventIngestService;
  sink: CollectingSink;
} {
  const repository = new InMemoryEventRepository();
  const sink = new CollectingSink();
  const notifier = new NotificationService(sink);
  const service = new EventIngestService(
    repository,
    notifier,
    Object.values(VN_ENTITIES),
  );

  return { repository, service, sink };
}
