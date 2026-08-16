import type { EventNotifier } from "../../application/ports/event-notifier.js";
import type { Event } from "../../domain/event.js";
import type { VNEntity } from "../../domain/vn.js";

export interface NotificationMessage {
  readonly locale: "zh-TW";
  readonly title: string;
  readonly body: string;
  readonly url: string;
}

export interface NotificationSink {
  send(message: NotificationMessage): Promise<void>;
}

export class NotificationService implements EventNotifier {
  constructor(private readonly sink: NotificationSink) {}

  async notify(event: Event, vn: VNEntity): Promise<void> {
    await this.sink.send({
      locale: "zh-TW",
      title: `【${vn.name}】${event.title}`,
      body: `${event.summary ?? ""}\n${event.url}`,
      url: event.url,
    });
  }
}
