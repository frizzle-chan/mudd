"""EffectsCollector provides the template-facing API for emitting events."""

from mudd.events.observer import Observer
from mudd.events.types import (
    BroadcastEvent,
    ClearFocusSignal,
    DestroySignal,
    DispenseSignal,
    DropSignal,
    GrantCurrencyEvent,
    GrantEvent,
    GrantRandomEvent,
    PickupSignal,
    SetFocusSignal,
)


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
            amount: Amount of yen to grant (from house account)

        Returns:
            Empty string (allows inline use in templates)
        """
        if amount > 0:
            self._observer.notify(GrantCurrencyEvent(amount=amount))
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
