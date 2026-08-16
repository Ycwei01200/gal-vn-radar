export interface SteamNewsItemDto {
  readonly gid: string;
  readonly title: string;
  readonly url: string;
  readonly date: number;
  readonly contents: string;
}

export interface SteamAppNewsDto {
  readonly appid: number;
  readonly newsitems: readonly SteamNewsItemDto[];
}

export interface SteamNewsResponseDto {
  readonly appnews: SteamAppNewsDto;
}

export function parseSteamNewsResponse(
  payload: unknown,
  expectedAppId: number,
): SteamNewsResponseDto {
  if (!isRecord(payload)) {
    throw new Error(`Steam news payload for app ${expectedAppId} must be an object`);
  }

  const appnews = payload.appnews;

  if (!isRecord(appnews)) {
    throw new Error(`Steam news payload for app ${expectedAppId} is missing appnews`);
  }

  if (appnews.appid !== expectedAppId) {
    throw new Error(`Steam news payload for app ${expectedAppId} has an unexpected app ID`);
  }

  if (!Array.isArray(appnews.newsitems)) {
    throw new Error(`Steam news payload for app ${expectedAppId} is missing newsitems`);
  }

  return {
    appnews: {
      appid: expectedAppId,
      newsitems: appnews.newsitems.map((item, index) =>
        parseSteamNewsItem(item, expectedAppId, index),
      ),
    },
  };
}

function parseSteamNewsItem(
  payload: unknown,
  expectedAppId: number,
  index: number,
): SteamNewsItemDto {
  if (!isRecord(payload)) {
    throw new Error(
      `Steam news item ${index} for app ${expectedAppId} must be an object`,
    );
  }

  const { gid, title, url, date, contents } = payload;

  if (
    typeof gid !== "string" ||
    typeof title !== "string" ||
    typeof url !== "string" ||
    typeof date !== "number" ||
    !Number.isFinite(date) ||
    typeof contents !== "string"
  ) {
    throw new Error(`Steam news item ${index} for app ${expectedAppId} is malformed`);
  }

  return { gid, title, url, date, contents };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
