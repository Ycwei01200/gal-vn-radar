import type { Event } from "../../domain/event.js";
import type { VNEntity } from "../../domain/vn.js";

export interface EventNotifier {
  notify(event: Event, vn: VNEntity): Promise<void>;
}
