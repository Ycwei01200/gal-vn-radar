import { VN_ENTITIES } from "./vn-entities.js";

export interface SteamAppMapping {
  readonly appId: number;
  readonly vnId: string;
}

export const STEAM_APP_MAPPINGS: readonly SteamAppMapping[] = [
  { appId: 324160, vnId: VN_ENTITIES.clannad.id },
  { appId: 303310, vnId: VN_ENTITIES.fataMorgana.id },
];
