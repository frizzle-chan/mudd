"""EffectsObserver collects game events during template rendering."""

from dataclasses import dataclass, field

from mudd.events.types import (
    BroadcastEvent,
    DestroySignal,
    DispenseSignal,
    DropSignal,
    GameEvent,
    GrantCurrencyEvent,
    GrantEvent,
    GrantRandomEvent,
    PickupSignal,
)


@dataclass
class EffectsObserver:
    """Collects game events during template rendering.

    The observer collects events synchronously during rendering and provides
    properties for the cog to check and process after sending the response.

    The flush() method is a no-op since the cog handles the actual side effects
    (sending broadcasts, processing grants, etc.).

    Usage:
        effects = EffectsObserver()
        collector = EffectsCollector(effects)
        output = render(template, effects=collector)

        # After sending response
        for msg in effects.broadcasts:
            await channel.send(msg)
        if effects.has_pickup:
            await move_to_inventory(...)
    """

    _broadcasts: list[str] = field(default_factory=list)
    _grants: list[str] = field(default_factory=list)
    _grant_randoms: list[str] = field(default_factory=list)
    _currency_grants: list[int] = field(default_factory=list)
    _pickup_signaled: bool = False
    _drop_signaled: bool = False
    _destroy_signaled: bool = False
    _dispense_signaled: bool = False

    def notify(self, event: GameEvent) -> None:
        """Receive an event notification.

        Args:
            event: The game event to process
        """
        match event:
            case BroadcastEvent(message=message):
                self._broadcasts.append(message)
            case GrantEvent(entity_id=entity_id):
                self._grants.append(entity_id)
            case GrantRandomEvent(tag=tag):
                self._grant_randoms.append(tag)
            case GrantCurrencyEvent(amount=amount):
                self._currency_grants.append(amount)
            case PickupSignal():
                self._pickup_signaled = True
            case DropSignal():
                self._drop_signaled = True
            case DestroySignal():
                self._destroy_signaled = True
            case DispenseSignal():
                self._dispense_signaled = True

    async def flush(self) -> None:
        """Flush pending operations (no-op for EffectsObserver).

        The cog handles the actual side effects; this observer just collects.
        """
        pass

    @property
    def broadcasts(self) -> list[str]:
        """Messages to broadcast publicly to the channel."""
        return self._broadcasts

    @property
    def grants(self) -> list[str]:
        """Entity IDs to grant to the user."""
        return self._grants

    @property
    def grant_randoms(self) -> list[str]:
        """Tags to randomly grant items from."""
        return self._grant_randoms

    @property
    def currency_grants(self) -> list[int]:
        """Amounts of currency to grant."""
        return self._currency_grants

    @property
    def has_pickup(self) -> bool:
        """Whether pickup() was called during template rendering."""
        return self._pickup_signaled

    @property
    def has_drop(self) -> bool:
        """Whether drop() was called during template rendering."""
        return self._drop_signaled

    @property
    def has_destroy(self) -> bool:
        """Whether destroy() was called during template rendering."""
        return self._destroy_signaled

    @property
    def has_dispense(self) -> bool:
        """Whether dispense() was called during template rendering."""
        return self._dispense_signaled

    def merge_from(self, other: "EffectsObserver") -> None:
        """Merge effects from another observer into this one.

        Used when processing dispense: the dispensed item's on_take effects
        are merged into the main effects for unified processing.

        Note: pickup/drop flags are NOT merged - they apply to the triggered
        item and are handled separately by the caller.

        Args:
            other: EffectsObserver to merge from
        """
        self._broadcasts.extend(other._broadcasts)
        self._grants.extend(other._grants)
        self._grant_randoms.extend(other._grant_randoms)
        self._currency_grants.extend(other._currency_grants)
        # OR flags together for destroy only (pickup/drop not merged)
        if other._destroy_signaled:
            self._destroy_signaled = True
