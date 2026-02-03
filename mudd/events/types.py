"""Event dataclasses for the observer pattern."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mudd.models.entity import EntityInstance


@dataclass(frozen=True)
class BroadcastEvent:
    """A message to broadcast publicly to the channel."""

    message: str


@dataclass(frozen=True)
class GrantEvent:
    """Grant a specific entity to the user."""

    entity_id: str


@dataclass(frozen=True)
class GrantRandomEvent:
    """Grant a random entity from a tag."""

    tag: str


@dataclass(frozen=True)
class GrantCurrencyEvent:
    """Grant currency to the user."""

    amount: int


@dataclass(frozen=True)
class PickupSignal:
    """Signal that the current item should be picked up."""

    pass


@dataclass(frozen=True)
class DropSignal:
    """Signal that the current item should be dropped."""

    pass


@dataclass(frozen=True)
class DestroySignal:
    """Signal that the current entity should be destroyed."""

    pass


@dataclass(frozen=True)
class DispenseSignal:
    """Signal that an item should be dispensed from this container."""

    pass


@dataclass(frozen=True)
class EntityPickedUpEvent:
    """Fact: entity was picked up by a user."""

    instance: "EntityInstance"


@dataclass(frozen=True)
class EntityDroppedEvent:
    """Fact: entity was dropped to a room."""

    instance: "EntityInstance"


@dataclass(frozen=True)
class EntityDestroyedEvent:
    """Fact: entity was destroyed."""

    instance: "EntityInstance"


@dataclass(frozen=True)
class ZoneSyncedEvent:
    """Zone was synced to database (created or updated)."""

    zone_id: str
    name: str


@dataclass(frozen=True)
class RoomSyncedEvent:
    """Room was synced to database (created or updated)."""

    room_id: str
    name: str
    description: str
    zone_id: str
    has_voice: bool


@dataclass(frozen=True)
class OrphanChannelDetectedEvent:
    """Orphan channel detected during sync."""

    guild_id: int
    channel_name: str
    category_name: str


@dataclass(frozen=True)
class WalletEnsuredEvent:
    """Wallet was created or verified for a user."""

    user_id: int
    instance: "EntityInstance"
    is_new: bool  # True if newly created, False if already existed


@dataclass(frozen=True)
class BalanceChangedEvent:
    """User's balance changed (for future use by economy cog)."""

    user_id: int
    new_balance: int
    delta: int  # Positive for credit, negative for debit
    memo: str


GameEvent = (
    BroadcastEvent
    | GrantEvent
    | GrantRandomEvent
    | GrantCurrencyEvent
    | PickupSignal
    | DropSignal
    | DestroySignal
    | DispenseSignal
    | EntityPickedUpEvent
    | EntityDroppedEvent
    | EntityDestroyedEvent
    | ZoneSyncedEvent
    | RoomSyncedEvent
    | OrphanChannelDetectedEvent
    | WalletEnsuredEvent
    | BalanceChangedEvent
)
