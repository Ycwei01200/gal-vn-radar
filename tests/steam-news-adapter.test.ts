import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

import {
  STEAM_APP_MAPPINGS,
  type SteamAppMapping,
} from "../src/config/steam-app-mappings.js";
import { VN_ENTITIES } from "../src/config/vn-entities.js";
import { SteamNewsAdapter } from "../src/infrastructure/steam/steam-news-adapter.js";

interface SteamFixture {
  readonly appnews: {
    readonly appid: number;
    readonly newsitems: readonly SteamFixtureItem[];
  };
}

interface SteamFixtureItem {
  readonly gid: string;
  readonly title: string;
  readonly url: string;
  readonly date: number;
  readonly contents: string;
  readonly feedname: string;
}

describe("STEAM_APP_MAPPINGS", () => {
  it("maps the supported Steam apps to VN entities", () => {
    expect(STEAM_APP_MAPPINGS).toEqual([
      { appId: 324160, vnId: VN_ENTITIES.clannad.id },
      { appId: 303310, vnId: VN_ENTITIES.fataMorgana.id },
    ]);
  });
});

describe("SteamNewsAdapter", () => {
  it("fetches mapped apps once each and normalizes Steam news into events", async () => {
    const requests: string[] = [];
    const clannadFixture = await loadFixture("clannad.json");
    const fataMorganaFixture = await loadFixture("fata-morgana.json");

    const adapter = new SteamNewsAdapter(STEAM_APP_MAPPINGS, {
      fetchImpl: async (input) => {
        const url = String(input);
        requests.push(url);

        if (url.includes("appid=324160")) {
          return jsonResponse(clannadFixture);
        }

        if (url.includes("appid=303310")) {
          return jsonResponse(fataMorganaFixture);
        }

        throw new Error(`unexpected URL: ${url}`);
      },
    });

    await expect(adapter.fetchEvents()).resolves.toEqual([
      {
        vnId: "vn-clannad",
        kind: "news",
        source: "steam",
        sourceEventId: "steam-gid-1",
        title: "Major Update",
        summary: "Update details",
        url: "https://steamcommunity.com/news/steam-gid-1",
        publishedAt: "2026-08-15T00:00:00.000Z",
        metadata: { appId: "324160" },
      },
      {
        vnId: "vn-fata-morgana",
        kind: "news",
        source: "steam",
        sourceEventId: "steam-gid-2",
        title: "Anniversary Story Update",
        summary: "New side stories are now available.",
        url: "https://steamcommunity.com/news/steam-gid-2",
        publishedAt: "2024-03-29T00:00:00.000Z",
        metadata: { appId: "303310" },
      },
    ]);

    expect(requests).toHaveLength(2);
    expect(requests).toContain(
      "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=324160&count=20&maxlength=300&format=json",
    );
    expect(requests).toContain(
      "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=303310&count=20&maxlength=300&format=json",
    );
  });

  it("only requests mapped app IDs and returns events for those mappings", async () => {
    const requests: string[] = [];
    const clannadFixture = await loadFixture("clannad.json");
    const mappings: readonly SteamAppMapping[] = [
      { appId: 324160, vnId: VN_ENTITIES.clannad.id },
    ];

    const adapter = new SteamNewsAdapter(mappings, {
      fetchImpl: async (input) => {
        const url = String(input);
        requests.push(url);

        if (url.includes("appid=324160")) {
          return jsonResponse(clannadFixture);
        }

        throw new Error(`unexpected URL: ${url}`);
      },
    });

    const events = await adapter.fetchEvents();

    expect(events).toHaveLength(1);
    expect(events[0]?.vnId).toBe("vn-clannad");
    expect(requests).toEqual([
      "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=324160&count=20&maxlength=300&format=json",
    ]);
    expect(requests.some((url) => url.includes("appid=999999"))).toBe(false);
  });

  it("deduplicates repeated Steam items with the same gid", async () => {
    const clannadFixture = await loadFixture("clannad.json");
    const duplicateFixture: SteamFixture = {
      appnews: {
        ...clannadFixture.appnews,
        newsitems: [
          ...clannadFixture.appnews.newsitems,
          {
            ...clannadFixture.appnews.newsitems[0],
            title: "Major Update (duplicate title ignored)",
          },
        ],
      },
    };

    const adapter = new SteamNewsAdapter(
      [{ appId: 324160, vnId: VN_ENTITIES.clannad.id }],
      {
        fetchImpl: async () => jsonResponse(duplicateFixture),
      },
    );

    const events = await adapter.fetchEvents();

    expect(events).toHaveLength(1);
    expect(events[0]?.sourceEventId).toBe("steam-gid-1");
  });

  it("rejects non-OK responses with the app ID in the error", async () => {
    const adapter = new SteamNewsAdapter(
      [{ appId: 324160, vnId: VN_ENTITIES.clannad.id }],
      {
        fetchImpl: async () =>
          new Response("steam unavailable", {
            status: 503,
            statusText: "Service Unavailable",
          }),
      },
    );

    await expect(adapter.fetchEvents()).rejects.toThrow(/324160/);
  });

  it("rejects malformed payloads with the app ID in the error", async () => {
    const adapter = new SteamNewsAdapter(
      [{ appId: 324160, vnId: VN_ENTITIES.clannad.id }],
      {
        fetchImpl: async () =>
          jsonResponse({
            appnews: {
              appid: 324160,
              newsitems: "not-an-array",
            },
          }),
      },
    );

    await expect(adapter.fetchEvents()).rejects.toThrow(/324160/);
  });
});

async function loadFixture(name: string): Promise<SteamFixture> {
  const fixturePath = new URL(`./fixtures/steam-news/${name}`, import.meta.url);
  const contents = await readFile(fixturePath, "utf8");

  return JSON.parse(contents) as SteamFixture;
}

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}
