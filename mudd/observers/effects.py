"""EffectsObserver collects game events during template rendering."""

from dataclasses import dataclass, field

from mudd.events.observer import Observer
from mudd.events.types import (
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
    GrantXPSignal,
    PickupSignal,
    SetFocusSignal,
)
from mudd.skills.registry import Skill


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

    _forward_targets: tuple[Observer, ...] = ()
    _broadcasts: list[str] = field(default_factory=list)
    _grants: list[str] = field(default_factory=list)
    _grant_randoms: list[str] = field(default_factory=list)
    _currency_grants: list[int] = field(default_factory=list)
    _xp_grants: list[tuple[Skill, int]] = field(default_factory=list)
    _pickup_signaled: bool = False
    _drop_signaled: bool = False
    _destroy_signaled: bool = False
    _dispense_signaled: bool = False
    _set_focus_signaled: bool = False
    _clear_focus_signaled: bool = False

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
            case GrantXPSignal(skill=skill, amount=amount):
                self._xp_grants.append((skill, amount))
            case PickupSignal():
                self._pickup_signaled = True
            case DropSignal():
                self._drop_signaled = True
            case DestroySignal():
                self._destroy_signaled = True
            case DispenseSignal():
                self._dispense_signaled = True
            case SetFocusSignal():
                self._set_focus_signaled = True
            case ClearFocusSignal():
                self._clear_focus_signaled = True
            case EntityPickedUpEvent() | EntityDroppedEvent() | EntityDestroyedEvent():
                pass  # Model events - handled by DiscordReconciler

    async def flush(self) -> None:
        """Forward collected XP grants to other observers.

        Iterates _xp_grants and notifies each forward target so that
        SkillsObserver (and others) receive GrantXPSignal without
        Scene.execute() reaching into observer state.
        """
        for skill, amount in self._xp_grants:
            for target in self._forward_targets:
                target.notify(GrantXPSignal(skill=skill, amount=amount))

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
    def xp_grants(self) -> list[tuple[Skill, int]]:
        """XP grants as (skill, amount) tuples."""
        return self._xp_grants

    @property
    def has_xp_grants(self) -> bool:
        """Whether any XP grants were signaled during template rendering."""
        return len(self._xp_grants) > 0

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

    @property
    def has_set_focus(self) -> bool:
        """Whether set_focus() was called during template rendering."""
        return self._set_focus_signaled

    @property
    def has_clear_focus(self) -> bool:
        """Whether clear_focus() was called during template rendering."""
        return self._clear_focus_signaled
