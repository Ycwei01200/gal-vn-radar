from gal_radar.database import EventRecord, EventStore
from gal_radar.models.event import NormalizedEvent


def find_duplicate(store: EventStore, event: NormalizedEvent) -> EventRecord | None:
    return store.find_equivalent(event)
