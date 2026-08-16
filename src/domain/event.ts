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

export function eventKeys(event: Event): readonly string[] {
  const normalizedUrl = normalizeUrl(event.url);
  const normalizedTitle = normalizeTitle(event.title);
  const publishedDay = new Date(event.publishedAt).toISOString().slice(0, 10);

  const keys = [
    `${event.vnId}|${event.kind}|title|${normalizedTitle}|day|${publishedDay}`,
    `${event.vnId}|${event.kind}|source|${event.source}|${event.sourceEventId}`,
  ];

  return normalizedUrl === ""
    ? keys
    : [
        `${event.vnId}|${event.kind}|url|${normalizedUrl}`,
        ...keys,
      ];
}

function normalizeUrl(url: string): string {
  const trimmed = url.trim();

  if (trimmed === "") {
    return "";
  }

  try {
    const parsed = new URL(trimmed);

    parsed.hostname = parsed.hostname.toLowerCase();
    return parsed.toString().replace(/\/$/, "");
  } catch {
    return trimmed.replace(/\/$/, "");
  }
}

function normalizeTitle(title: string): string {
  return title
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}
