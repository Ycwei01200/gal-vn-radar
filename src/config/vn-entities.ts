import type { VNEntity } from "../domain/vn.js";

export const VN_ENTITIES = {
  clannad: { id: "vn-clannad", name: "CLANNAD" },
  fataMorgana: { id: "vn-fata-morgana", name: "The House in Fata Morgana" },
} as const satisfies Record<string, VNEntity>;
