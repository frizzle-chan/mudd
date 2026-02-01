"""Event dataclasses for the observer pattern."""

from dataclasses import dataclass


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


GameEvent = (
    BroadcastEvent
    | GrantEvent
    | GrantRandomEvent
    | GrantCurrencyEvent
    | PickupSignal
    | DropSignal
    | DestroySignal
    | DispenseSignal
)
