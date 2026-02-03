"""Events package for the observer pattern.

This package provides the event types, observer protocol, and collector
for the effects system. Templates emit events through an EffectsCollector,
which notifies observers that collect and process the events.
"""

from mudd.events.collector import EffectsCollector
from mudd.events.observer import Observer, OutputObserver
from mudd.events.types import (
    BroadcastEvent,
    DestroySignal,
    DispenseSignal,
    DropSignal,
    EntityDestroyedEvent,
    EntityDroppedEvent,
    EntityPickedUpEvent,
    GameEvent,
    GrantCurrencyEvent,
    GrantEvent,
    GrantRandomEvent,
    OrphanChannelDetectedEvent,
    PickupSignal,
    RoomSyncedEvent,
    ZoneSyncedEvent,
)

__all__ = [
    # Collector
    "EffectsCollector",
    # Observer protocols
    "Observer",
    "OutputObserver",
    # Event types
    "GameEvent",
    "BroadcastEvent",
    "GrantEvent",
    "GrantRandomEvent",
    "GrantCurrencyEvent",
    "PickupSignal",
    "DropSignal",
    "DestroySignal",
    "DispenseSignal",
    "EntityPickedUpEvent",
    "EntityDroppedEvent",
    "EntityDestroyedEvent",
    "ZoneSyncedEvent",
    "RoomSyncedEvent",
    "OrphanChannelDetectedEvent",
]
