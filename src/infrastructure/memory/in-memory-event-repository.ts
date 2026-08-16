import { eventKeys, type Event } from "../../domain/event.js";
import type { EventRepository } from "../../application/ports/event-repository.js";

export class InMemoryEventRepository implements EventRepository {
  private readonly events: Event[] = [];

  async hasEquivalent(event: Event): Promise<boolean> {
    const candidateKeys = new Set(eventKeys(event));

    return this.events.some((storedEvent) =>
      eventKeys(storedEvent).some((storedKey) => candidateKeys.has(storedKey)),
    );
  }

  async add(event: Event): Promise<void> {
    this.events.push(event);
  }

  async list(): Promise<readonly Event[]> {
    return [...this.events];
  }
}
