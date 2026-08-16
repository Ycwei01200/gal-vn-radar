import type { SourceAdapter } from "../../application/ports/source-adapter.js";
import { eventKeys, type Event } from "../../domain/event.js";
import type { SteamAppMapping } from "../../config/steam-app-mappings.js";
import { parseSteamNewsResponse } from "./steam-news-types.js";

export interface SteamNewsAdapterOptions {
  readonly count?: number;
  readonly maxLength?: number;
  readonly fetchImpl?: typeof fetch;
}

export class SteamNewsAdapter implements SourceAdapter {
  readonly source = "steam";

  readonly #count: number;
  readonly #fetchImpl: typeof fetch;
  readonly #mappings: readonly SteamAppMapping[];
  readonly #maxLength: number;

  constructor(
    mappings: readonly SteamAppMapping[],
    options: SteamNewsAdapterOptions = {},
  ) {
    this.#mappings = mappings;
    this.#count = options.count ?? 20;
    this.#maxLength = options.maxLength ?? 300;
    this.#fetchImpl = options.fetchImpl ?? fetch;
  }

  async fetchEvents(): Promise<readonly Event[]> {
    const events: Event[] = [];
    const seenKeys = new Set<string>();

    for (const mapping of this.#mappings) {
      const response = await this.#fetchImpl(this.#buildUrl(mapping.appId));

      if (!response.ok) {
        throw new Error(
          `Steam news request failed for app ${mapping.appId}: ${response.status} ${response.statusText}`.trim(),
        );
      }

      const payload = await response.json();
      const parsed = parseSteamNewsResponse(payload, mapping.appId);

      for (const item of parsed.appnews.newsitems) {
        const event = this.#toEvent(mapping, item);
        const keys = eventKeys(event);

        if (keys.some((key) => seenKeys.has(key))) {
          continue;
        }

        for (const key of keys) {
          seenKeys.add(key);
        }

        events.push(event);
      }
    }

    return events;
  }

  #buildUrl(appId: number): string {
    return `https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=${appId}&count=${this.#count}&maxlength=${this.#maxLength}&format=json`;
  }

  #toEvent(
    mapping: SteamAppMapping,
    item: ReturnType<typeof parseSteamNewsResponse>["appnews"]["newsitems"][number],
  ): Event {
    return {
      vnId: mapping.vnId,
      kind: "news",
      source: this.source,
      sourceEventId: item.gid,
      title: item.title.trim(),
      summary: normalizeSummary(item.contents),
      url: item.url,
      publishedAt: new Date(item.date * 1000).toISOString(),
      metadata: { appId: String(mapping.appId) },
    };
  }
}

function normalizeSummary(contents: string): string | null {
  const trimmed = contents.trim();
  return trimmed === "" ? null : trimmed;
}
