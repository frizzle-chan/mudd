"""EffectsCollector provides the template-facing API for emitting events."""

import logging

from mudd.events.observer import Observer
from mudd.events.types import (
    BroadcastEvent,
    ChargeCurrencySignal,
    ClearFocusSignal,
    DestroySignal,
    DispenseSignal,
    DropSignal,
    GrantCurrencyEvent,
    GrantEvent,
    GrantRandomEvent,
    GrantXPSignal,
    PickupSignal,
    SetFocusSignal,
    ShopSignal,
)
from mudd.skills.registry import Skill

logger = logging.getLogger(__name__)


class EffectsCollector:
    """Template-facing interface for emitting game events.

    Wraps an Observer and provides the familiar effects API for templates:

        {{ effects.broadcast("**" ~ user.name ~ "** put on music.") }}
        {{ effects.pickup() }}

    All methods return empty string to allow inline use in Jinja templates.
    """

    def __init__(self, observer: Observer) -> None:
        """Initialize with an observer to receive events.

        Args:
            observer: The observer that will receive emitted events
        """
        self._observer = observer

    def broadcast(self, message: str) -> str:
        """Queue a message to broadcast publicly to the channel.

        Args:
            message: Message to send (empty/None ignored)

        Returns:
            Empty string (allows inline use in templates)
        """
        if message:
            self._observer.notify(BroadcastEvent(message=message))
        return ""

    def pickup(self) -> str:
        """Signal that this item should be picked up.

        Returns:
            Empty string (allows inline use in templates)
        """
        self._observer.notify(PickupSignal())
        return ""

    def drop(self) -> str:
        """Signal that this item should be dropped.

        Returns:
            Empty string (allows inline use in templates)
        """
        self._observer.notify(DropSignal())
        return ""

    def destroy(self) -> str:
        """Signal that this entity should be destroyed.

        Returns:
            Empty string (allows inline use in templates)
        """
        self._observer.notify(DestroySignal())
        return ""

    def grant(self, entity_id: str) -> str:
        """Queue granting a specific item to the user.

        Args:
            entity_id: ID of the entity to grant

        Returns:
            Empty string (allows inline use in templates)
        """
        if entity_id:
            self._observer.notify(GrantEvent(entity_id=entity_id))
        return ""

    def grant_random(self, tag: str) -> str:
        """Queue granting a random item from entities with the given tag.

        Args:
            tag: Tag to filter entities by

        Returns:
            Empty string (allows inline use in templates)
        """
        if tag:
            self._observer.notify(GrantRandomEvent(tag=tag))
        return ""

    def grant_currency(self, amount: int) -> str:
        """Queue granting currency to the user.

        Args:
            amount: Amount to grant (from house account)

        Returns:
            Empty string (allows inline use in templates)
        """
        if amount > 0:
            self._observer.notify(GrantCurrencyEvent(amount=amount))
        return ""

    def charge(self, amount: int) -> str:
        """Queue a currency charge (debit) from the user.

        Args:
            amount: Amount to charge (debited to house account)

        Returns:
            Empty string (allows inline use in templates)
        """
        if amount > 0:
            self._observer.notify(ChargeCurrencySignal(amount=amount))
        return ""

    def grant_xp(self, skill: str, amount: int) -> str:
        """Queue granting XP in a skill to the user.

        Args:
            skill: The skill to grant XP in (validated against Skill enum)
            amount: Amount of XP to grant

        Returns:
            Empty string (allows inline use in templates)
        """
        if skill and amount > 0:
            try:
                validated = Skill(skill)
            except ValueError:
                logger.warning("Invalid skill name in grant_xp: %r", skill)
                return ""
            self._observer.notify(GrantXPSignal(skill=validated, amount=amount))
        return ""

    def dispense(self) -> str:
        """Signal that an item should be dispensed from this container.

        Returns:
            Empty string (allows inline use in templates)
        """
        self._observer.notify(DispenseSignal())
        return ""

    def set_focus(self) -> str:
        """Signal that focus should be set on the current entity.

        Returns:
            Empty string (allows inline use in templates)
        """
        self._observer.notify(SetFocusSignal())
        return ""

    def clear_focus(self) -> str:
        """Signal that user focus should be cleared.

        Returns:
            Empty string (allows inline use in templates)
        """
        self._observer.notify(ClearFocusSignal())
        return ""

    def shop(self, shop_id: str) -> str:
        """Signal that a trading session should open with a shop.

        Args:
            shop_id: ID of the shop to open

        Returns:
            Empty string (allows inline use in templates)
        """
        if shop_id:
            self._observer.notify(ShopSignal(shop_id=shop_id))
        return ""
