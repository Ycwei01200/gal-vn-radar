import { describe, expect, it } from "vitest";

import { eventKeys, type Event } from "../src/domain/event.js";

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

describe("eventKeys", () => {
  it("uses canonical URL as the strongest cross-source key", () => {
    expect(eventKeys(event("https://steamcommunity.com/news/42"))[0]).toBe(
      "vn-clannad|news|url|https://steamcommunity.com/news/42",
    );
  });

  it("falls back to normalized title and UTC publication day", () => {
    expect(eventKeys(event(""))[0]).toBe(
      "vn-clannad|news|title|major update|day|2026-08-15",
    );
  });

  it("keeps source identity as a same-source duplicate guard", () => {
    expect(eventKeys(event(""))[1]).toBe(
      "vn-clannad|news|source|steam|gid-42",
    );
  });
});
