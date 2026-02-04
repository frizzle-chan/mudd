"""Events package for the observer pattern.

This package provides the event types, observer protocol, and collector
for the effects system. Templates emit events through an EffectsCollector,
which notifies observers that collect and process the events.
"""

from mudd.events.collector import EffectsCollector
from mudd.events.observer import Observer, OutputObserver
from mudd.events.types import (
    BalanceChangedEvent,
    BroadcastEvent,
    DestroySignal,
    DispenseSignal,
    DropSignal,
    EntityDestroyedEvent,
    EntityDroppedEvent,
    EntityPickedUpEvent,
    EntitySpawnedEvent,
    GameEvent,
    GrantCurrencyEvent,
    GrantEvent,
    GrantRandomEvent,
    InventorySyncEvent,
    OrphanChannelDetectedEvent,
    PickupSignal,
    RoomSyncedEvent,
    UserJoinedEvent,
    UserLeftEvent,
    UserLocationSyncEvent,
    UserMovedEvent,
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
    "EntitySpawnedEvent",
    "ZoneSyncedEvent",
    "RoomSyncedEvent",
    "OrphanChannelDetectedEvent",
    "BalanceChangedEvent",
    "InventorySyncEvent",
    "UserMovedEvent",
    "UserLocationSyncEvent",
    "UserJoinedEvent",
    "UserLeftEvent",
]
