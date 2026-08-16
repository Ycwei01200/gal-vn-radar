import type { SourceAdapter } from "../../application/ports/source-adapter.js";
import { eventKeys, type Event } from "../../domain/event.js";
import type { SteamAppMapping } from "../../config/steam-app-mappings.js";
import { parseSteamNewsResponse } from "./steam-news-types.js";

const MAX_NEWS_COUNT = 100;
const MAX_NEWS_LENGTH = 10_000;

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
    this.#count = boundedPositiveIntegerOption(
      options.count ?? 20,
      "count",
      MAX_NEWS_COUNT,
    );
    this.#maxLength = boundedPositiveIntegerOption(
      options.maxLength ?? 300,
      "maxLength",
      MAX_NEWS_LENGTH,
    );
    this.#fetchImpl = options.fetchImpl ?? fetch;
  }

  async fetchEvents(): Promise<readonly Event[]> {
    const events: Event[] = [];
    const seenKeys = new Set<string>();

    for (const mapping of this.#mappings) {
      let response: Response;

      try {
        response = await this.#fetchImpl(this.#buildUrl(mapping.appId));
      } catch (error) {
        throw new Error(`Steam news request failed for app ${mapping.appId}`, {
          cause: error,
        });
      }

      if (!response.ok) {
        throw new Error(
          `Steam news request failed for app ${mapping.appId}: ${response.status} ${response.statusText}`.trim(),
        );
      }

      let parsed: ReturnType<typeof parseSteamNewsResponse>;

      try {
        const payload = await response.json();
        parsed = parseSteamNewsResponse(payload, mapping.appId);
      } catch (error) {
        throw new Error(
          `Steam news payload failed for app ${mapping.appId}`,
          { cause: error },
        );
      }

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

function boundedPositiveIntegerOption(
  value: number,
  name: string,
  maximum: number,
): number {
  if (!Number.isSafeInteger(value) || value <= 0 || value > maximum) {
    throw new Error(
      `Steam news ${name} must be an integer between 1 and ${maximum}`,
    );
  }

  return value;
}

function normalizeSummary(contents: string): string | null {
  const trimmed = contents.trim();
  return trimmed === "" ? null : trimmed;
}
