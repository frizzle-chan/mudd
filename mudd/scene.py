from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, TypeVar

import asyncpg
import discord
from discord import Interaction

from mudd.events import Observer
from mudd.models.entity import EntityInstance
from mudd.models.interfaces import IRoom
from mudd.models.room import EntityModal, InventoryThread, Room
from mudd.models.user import User
from mudd.observers import EffectsObserver

if TYPE_CHECKING:
    from mudd.commands import ActionCommand, ActionResult

T = TypeVar("T")


@dataclass(frozen=True)
class Scene:
    """Scene represents the current context for a user's interaction.

    Contains the user, their current room/focus, and attached observers
    that collect events during command execution.
    """

    user: User
    room: IRoom
    _pool: asyncpg.Pool = field(repr=False, compare=False, default=None)  # ty:ignore[invalid-assignment]
    _observers: tuple[Observer, ...] = field(default=(), repr=False, compare=False)

    # room and inventory share an interface
    # rooms and inventories fill the scene
    #
    # entities are the entities the user can see
    # entities the user can see are the entities the user is focused on
    # if no focus, implicitly focus on the room
    #
    # interaction is scene(user, room, entities) + command(entity) = outcome
    # a room is an entity just like in a 3d program where the room is modeled object
    # room is a virtual entity

    @classmethod
    async def from_interaction(
        cls, pool: asyncpg.Pool, interaction: Interaction
    ) -> Scene:
        user = await User.get(pool, interaction.user.id)
        if not user:
            raise ValueError("User not found")

        if isinstance(interaction.channel, discord.Thread) and (
            inventory_entity := await EntityInstance.get_by_inventory_thread_id(
                pool, interaction.channel.id
            )
        ):
            if inventory_entity.owner_id != user.id:
                raise ValueError("User does not own this inventory thread")
            room = InventoryThread(
                _pool=pool,
                id=str(interaction.channel.id),
                entity_instance=inventory_entity,
                owner=user,
            )
        elif focus := await user.get_focus():
            room = EntityModal(
                _pool=pool,
                id=f"Focus:{focus.current_container.instance_id}",
                zone_id="Focus",
                entity_instance=focus.current_container,
                is_container=True,
            )
        else:
            room = await Room.get(pool, user.current_room)
            if not room:
                raise ValueError("User is in an invalid room")
        return cls(_pool=pool, user=user, room=room)

    async def contains(self, entity: EntityInstance) -> bool:
        """Check if the scene contains the given entity instance."""
        # Check if the entity is in the room
        visible = {e.instance_id for e in await self.room.get_visible_entities()}
        inventory = {e.instance_id for e in await self.user.get_inventory()}
        return entity.instance_id in visible | inventory

    async def other_players(self) -> list[User]:
        """Get other players in the same room (excluding self)."""
        all_players = await User.get_players_in_room(self._pool, self.user.current_room)
        return [p for p in all_players if p.id != self.user.id]

    def with_observers(self, *observers: Observer) -> Scene:
        """Return a new Scene with the given observers attached.

        Also propagates observers to the scene's user, so user mutations
        (like transfer_currency_to) emit events to attached observers.

        Args:
            observers: Observer instances to attach

        Returns:
            New Scene with observers attached to both scene and user
        """
        new_observers = self._observers + observers
        new_user = self.user.with_observers(*new_observers)
        return replace(self, _observers=new_observers, user=new_user)

    def get_observer(self, cls: type[T]) -> T | None:
        """Get an attached observer by type.

        Args:
            cls: The observer class to find

        Returns:
            The observer instance if found, None otherwise
        """
        for observer in self._observers:
            if isinstance(observer, cls):
                return observer
        return None

    async def flush_observers(self) -> None:
        """Flush all attached observers.

        Call this after the response is sent to execute any pending
        side effects collected during command execution.
        """
        for observer in self._observers:
            await observer.flush()

    async def execute(
        self, command: ActionCommand, target: EntityInstance
    ) -> ActionResult:
        """Execute a command and process all effects.

        1. Attach scene observers to target entity
        2. Run command (collects signals via EffectsObserver)
        3. Map signals to entity mutations (pickup → move_to_inventory)
        4. Entity mutations emit events to all observers
        5. Flush observers (Discord thread creation, etc.)
        6. Return result

        Args:
            command: The action command to execute
            target: The entity instance to act upon

        Returns:
            ActionResult with rendered output
        """
        effects = self.get_observer(EffectsObserver)
        if not effects:
            raise ValueError("EffectsObserver not attached to scene")

        # Attach scene observers to target so mutations notify them
        target = target.with_observers(*self._observers)

        result = await command.execute(self, target)

        # Map signals to actions
        if effects.has_pickup:
            await target.move_to_inventory(self.user)
        if effects.has_drop:
            drop_room = await self.room.get_drop_target()
            if drop_room:
                await target.drop_to_room(drop_room)
        if effects.has_destroy:
            await target.destroy()

        return result
