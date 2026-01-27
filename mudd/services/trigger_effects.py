"""Side effects collected during template rendering."""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID


@dataclass
class GrantEffect:
    """A queued grant of a specific item."""

    entity_id: str


@dataclass
class GrantRandomEffect:
    """A queued random grant from a tag."""

    tag: str


@dataclass
class CurrencyGrantEffect:
    """A queued currency grant."""

    amount: int


@dataclass
class CleanupOperation:
    """A deferred cleanup operation to run after response."""

    operation_type: Literal["delete_thread"]
    instance_id: UUID
    guild_id: int


@dataclass
class TriggerEffects:
    """Collects side effects during template rendering.

    Templates can call methods on this object to queue side effects
    that will be executed after the template renders:

    - `broadcast(message)`: Queue a message to send publicly to the channel
    - `drop()`: Queue dropping the current item from inventory to room
    - `pickup()`: Signal that item should be picked up (move from room to inventory)
    - `grant(entity_id)`: Queue granting a specific item to the user
    - `grant_random(tag)`: Queue granting a random item from a tag (broadcasts result)
    - `grant_currency(amount)`: Queue granting currency from house account
    - `destroy()`: Signal that this entity instance should be destroyed
    - `dispense()`: Signal that an item should be dispensed from this container

    Example template:
        {{ effects.broadcast("**" ~ user.name ~ "** put on music.") }}
        You slide the record onto the turntable. Music fills the room.

    Result:
        - Ephemeral to user: "You slide the record onto the turntable..."
        - Public to channel: "**Frizzle** put on music."
    """

    broadcasts: list[str] = field(default_factory=list)
    _drop_called: bool = False
    _pickup_called: bool = False
    _destroy_called: bool = False
    _dispense_called: bool = False
    grants: list[GrantEffect] = field(default_factory=list)
    grant_randoms: list[GrantRandomEffect] = field(default_factory=list)
    currency_grants: list[CurrencyGrantEffect] = field(default_factory=list)
    cleanups: list[CleanupOperation] = field(default_factory=list)

    def broadcast(self, message: str) -> str:
        """Queue a message to broadcast publicly to the channel.

        Args:
            message: Message to send to the channel (empty/None ignored)

        Returns:
            Empty string (allows inline use in templates without output)
        """
        if message:
            self.broadcasts.append(message)
        return ""

    def drop(self) -> str:
        """Queue dropping the current item from inventory to room.

        Must be called in an on_drop handler. The item will be moved
        from the user's inventory to their current room.

        Returns:
            Empty string (allows inline use in templates without output)
        """
        self._drop_called = True
        return ""

    def pickup(self) -> str:
        """Signal that this item should be picked up.

        Must be called in an on_take handler. The item will be moved
        from the room to the user's inventory.

        Returns:
            Empty string (allows inline use in templates without output)
        """
        self._pickup_called = True
        return ""

    def grant(self, entity_id: str) -> str:
        """Queue granting a specific item to the user.

        Creates a new instance of the entity in the user's inventory.

        Args:
            entity_id: ID of the entity to grant

        Returns:
            Empty string (allows inline use in templates without output)
        """
        if entity_id:
            self.grants.append(GrantEffect(entity_id=entity_id))
        return ""

    def grant_random(self, tag: str) -> str:
        """Queue granting a random item from entities with the given tag.

        The actual selection and granting happens after template rendering.
        Uses weighted random selection based on rarity. Items with
        'none' rarity are excluded from random selection.

        If an item is granted, a broadcast message is sent to the channel
        so other players can see it.

        Args:
            tag: Tag to filter entities by

        Returns:
            Empty string (allows inline use in templates without output)
        """
        if tag:
            self.grant_randoms.append(GrantRandomEffect(tag=tag))
        return ""

    def grant_currency(self, amount: int) -> str:
        """Queue granting currency to the user.

        Args:
            amount: Amount of yen to grant (from house account)

        Returns:
            Empty string (allows inline use in templates)
        """
        if amount > 0:
            self.currency_grants.append(CurrencyGrantEffect(amount=amount))
        return ""

    @property
    def has_drop(self) -> bool:
        """Whether drop() was called during template rendering."""
        return self._drop_called

    @property
    def has_pickup(self) -> bool:
        """Whether pickup() was called during template rendering."""
        return self._pickup_called

    def destroy(self) -> str:
        """Signal that this entity instance should be destroyed.

        Must be called in an action handler (e.g., on_attack). The entity
        instance will be deleted from the database after the response is sent.

        Returns:
            Empty string (allows inline use in templates without output)
        """
        self._destroy_called = True
        return ""

    @property
    def has_destroy(self) -> bool:
        """Whether destroy() was called during template rendering."""
        return self._destroy_called

    def dispense(self) -> str:
        """Signal that an item should be dispensed from this container.

        Must be called in an action handler (e.g., on_use). The container
        will transfer a random item from its contents to the user's inventory.

        Returns:
            Empty string (allows inline use in templates without output)
        """
        self._dispense_called = True
        return ""

    @property
    def has_dispense(self) -> bool:
        """Whether dispense() was called during template rendering."""
        return self._dispense_called

    def queue_thread_deletion(self, instance_id: UUID, guild_id: int) -> None:
        """Queue a thread deletion to run after response.

        Args:
            instance_id: UUID of the entity instance whose thread to delete
            guild_id: Discord guild ID where the thread exists
        """
        self.cleanups.append(
            CleanupOperation(
                operation_type="delete_thread",
                instance_id=instance_id,
                guild_id=guild_id,
            )
        )
