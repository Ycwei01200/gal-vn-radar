import type { Event } from "../domain/event.js";
import type { VNEntity } from "../domain/vn.js";
import type { EventNotifier } from "./ports/event-notifier.js";
import type { EventRepository } from "./ports/event-repository.js";

export class EventIngestService {
  private readonly vnEntitiesById: ReadonlyMap<string, VNEntity>;

  constructor(
    private readonly repository: EventRepository,
    private readonly notifier: EventNotifier,
    vnEntities: readonly VNEntity[],
  ) {
    this.vnEntitiesById = new Map(
      vnEntities.map((vn) => [vn.id, vn] as const),
    );
  }

  async ingest(events: readonly Event[]): Promise<readonly Event[]> {
    const resolvedEvents = events.map((event) => ({
      event,
      vn: this.resolveVN(event.vnId),
    }));
    const accepted: Event[] = [];

    for (const { event, vn } of resolvedEvents) {
      if (await this.repository.hasEquivalent(event)) {
        continue;
      }

      await this.repository.add(event);
      await this.notifier.notify(event, vn);
      accepted.push(event);
    }

    return accepted;
  }

  private resolveVN(vnId: string): VNEntity {
    const vn = this.vnEntitiesById.get(vnId);

    if (vn === undefined) {
      throw new Error(`Unknown VN entity: ${vnId}`);
    }

    return vn;
  }
}
