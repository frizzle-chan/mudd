from __future__ import annotations

from dataclasses import dataclass, field

import asyncpg
import discord
from discord import Interaction

from mudd.models import EntityInstance, IRoom, Room, User
from mudd.models.room import EntityModal


@dataclass(frozen=True)
class Scene:
    """ """

    user: User
    room: IRoom
    _pool: asyncpg.Pool = field(repr=False, compare=False, default=None)  # ty:ignore[invalid-assignment]

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
            room = EntityModal(
                _pool=pool,
                id=str(interaction.channel.id),
                zone_id="Inventory",
                entity_instance=inventory_entity,
                allow_close=False,
            )
        elif focus := await user.get_focus():
            room = EntityModal(
                _pool=pool,
                id=f"Focus:{focus.current_container.instance_id}",
                zone_id="Focus",
                entity_instance=focus.current_container,
                allow_close=True,
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
