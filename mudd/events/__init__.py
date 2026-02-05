"""Events package for the observer pattern.

This package provides the event types, observer protocol, and collector
for the effects system. Templates emit events through an EffectsCollector,
which notifies observers that collect and process the events.
"""

from mudd.events.collector import EffectsCollector
from mudd.events.observer import Observer
from mudd.events.types import (
    BalanceChangedEvent,
    BroadcastEvent,
    ClearFocusSignal,
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
    InventorySyncEvent,
    OrphanChannelDetectedEvent,
    PickupSignal,
    RoomSyncedEvent,
    SetFocusSignal,
    UserJoinedEvent,
    UserLeftEvent,
    UserLocationSyncEvent,
    UserMovedEvent,
    UserSyncEvent,
    ZoneSyncedEvent,
)

__all__ = [
    # Collector
    "EffectsCollector",
    # Observer protocols
    "Observer",
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
    "SetFocusSignal",
    "ClearFocusSignal",
    "EntityPickedUpEvent",
    "EntityDroppedEvent",
    "EntityDestroyedEvent",
    "ZoneSyncedEvent",
    "RoomSyncedEvent",
    "OrphanChannelDetectedEvent",
    "BalanceChangedEvent",
    "InventorySyncEvent",
    "UserMovedEvent",
    "UserLocationSyncEvent",
    "UserSyncEvent",
    "UserJoinedEvent",
    "UserLeftEvent",
]
