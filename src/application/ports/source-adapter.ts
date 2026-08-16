import type { Event } from "../../domain/event.js";

export interface SourceAdapter {
  readonly source: string;
  fetchEvents(): Promise<readonly Event[]>;
}
