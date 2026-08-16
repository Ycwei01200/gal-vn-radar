import type { Event } from "../../domain/event.js";

export interface EventRepository {
  hasEquivalent(event: Event): Promise<boolean>;
  add(event: Event): Promise<void>;
  list(): Promise<readonly Event[]>;
}
