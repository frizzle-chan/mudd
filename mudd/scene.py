from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field, replace

import asyncpg
import discord
from discord import Interaction

from mudd.commands import ActionCommand, ActionResult, TakeCommand
from mudd.events import Observer
from mudd.models.entity import EntityInstance, ResolvedEntity
from mudd.models.interfaces import IReadableEntity, IRoom
from mudd.models.room import EntityModal, InventoryThread, Room
from mudd.models.user import InsufficientFundsError, User
from mudd.observers import EffectsObserver, build_observers, flush_all, post_flush_all
from mudd.views import ViewEntity

logger = logging.getLogger(__name__)


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
    async def build(
        cls,
        pool: asyncpg.Pool,
        interaction: Interaction,
        bot: discord.Client | None = None,
    ) -> Scene:
        """Build a Scene with standard observers attached.

        Creates a Scene from the interaction, attaches an EffectsObserver,
        and optionally a DiscordReconciler if a bot is provided.

        Args:
            pool: Database connection pool
            interaction: Discord interaction
            bot: Discord bot client (enables DiscordReconciler when provided)

        Returns:
            Scene with observers attached
        """
        scene = await cls.from_interaction(pool, interaction)
        observers = build_observers(
            pool, scene.user.id, scene.user.current_room, bot=bot
        )
        effects = EffectsObserver(_forward_targets=tuple(observers))
        scene = scene.with_observers(effects, *observers)
        return scene

    @classmethod
    async def from_user(
        cls, pool: asyncpg.Pool, user_id: int, *, thread_id: int | None = None
    ) -> Scene:
        """Build a Scene from database state without a Discord Interaction.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
            thread_id: Discord thread ID (enables InventoryThread context)

        Returns:
            Scene for the user's current context
        """
        user = await User.get(pool, user_id)
        if not user:
            raise ValueError("User not found")

        if thread_id is not None and (
            inventory_entity := await EntityInstance.get_by_inventory_thread_id(
                pool, thread_id
            )
        ):
            if inventory_entity.owner_id != user.id:
                raise ValueError("User does not own this inventory thread")
            room = InventoryThread(
                _pool=pool,
                id=str(thread_id),
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

    @classmethod
    async def from_interaction(
        cls, pool: asyncpg.Pool, interaction: Interaction
    ) -> Scene:
        thread_id = (
            interaction.channel.id
            if isinstance(interaction.channel, discord.Thread)
            else None
        )
        return await cls.from_user(pool, interaction.user.id, thread_id=thread_id)

    async def contains(self, entity: IReadableEntity) -> bool:
        """Check if the scene contains the given entity instance."""
        visible = {e.instance_id for e in await self.room.get_visible_entities()}
        inventory = {e.instance_id for e in await self.user.get_inventory()}
        room = {f"room://{self.user.current_room}"}
        return entity.instance_id in visible | inventory | room

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

    def get_observer[T](self, cls: type[T]) -> T | None:
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
        await flush_all(self._observers)
        await post_flush_all(self._observers)

    async def _take_item(self, item: IReadableEntity) -> ActionResult:
        """Execute TakeCommand on an item using a sub-scene.

        Creates a sub-scene with a fresh EffectsObserver (keeping other
        observers like DiscordReconciler) so sub-effects don't mix with
        the parent. Merges broadcasts back into the parent for the cog
        to send.

        Args:
            item: The entity instance to take

        Returns:
            ActionResult from the sub-scene's TakeCommand execution
        """
        parent_effects = self.get_observer(EffectsObserver)
        if not parent_effects:
            raise ValueError("EffectsObserver not attached to scene")

        # Build sub-scene with fresh EffectsObserver, keeping other observers
        sub_effects = EffectsObserver()
        other_observers = tuple(
            o for o in self._observers if not isinstance(o, EffectsObserver)
        )
        clean_user = replace(self.user, _observers=())
        sub_scene = replace(self, _observers=(), user=clean_user)
        sub_scene = sub_scene.with_observers(sub_effects, *other_observers)

        result = await sub_scene.execute(TakeCommand(), item)

        # Merge broadcasts and XP grants back so the parent can process them
        parent_effects._broadcasts.extend(sub_effects.broadcasts)
        parent_effects._xp_grants.extend(sub_effects._xp_grants)

        return result

    async def execute(
        self, command: ActionCommand, target: IReadableEntity
    ) -> ActionResult:
        """Execute a command and process all effects.

        1. Attach scene observers to target entity
        2. Run command (collects signals via EffectsObserver)
        3. Map signals to entity mutations (pickup → move_to_inventory)
        4. Entity mutations emit events to all observers
        5. Flush observers (Discord thread creation, etc.)
        6. Return result

        Commands validate capabilities before signaling effects. If a command
        signals an effect, the entity must support it. Mutation effects
        (pickup, drop, destroy, set_focus) only apply to EntityInstance targets.

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
        # (no-op for RoomEntityInstance since rooms don't emit events)
        target = target.with_observers(*self._observers)

        result = await command.execute(self.user, self.room, effects, target)

        # Apply effects - commands already validated capabilities

        # Currency charges: debit to house account (pay before receiving)
        view = ViewEntity(target)
        for amount in effects.currency_charges:
            try:
                await self.user.debit_to_house(amount, memo=f"Charged by {view.name}")
            except InsufficientFundsError:
                logger.warning(
                    "Charge of %d failed for user %d: insufficient funds",
                    amount,
                    self.user.id,
                )

        # Dispense: pick random item from container contents → _take_item
        if effects.has_dispense:
            contents = await target.get_contents()
            if contents:
                dispensed = random.choice(contents)
                sub_result = await self._take_item(dispensed)
                result = ActionResult(output=result.output + "\n" + sub_result.output)

        # Mutation effects only apply to database-backed entities
        if isinstance(target, EntityInstance):
            if effects.has_pickup:
                await target.move_to_inventory(self.user)
            if effects.has_drop:
                drop_room = await self.room.get_drop_target()
                if drop_room:
                    await target.drop_to_room(drop_room)
            if effects.has_destroy:
                await target.destroy()
            if effects.has_set_focus:
                await self.user.set_focus(target.instance_id)
        if effects.has_clear_focus:
            await self.user.clear_focus()

        # Currency grants: credit from house account
        for amount in effects.currency_grants:
            await self.user.credit_from_house(
                amount, memo=f"Picked up from {view.name}"
            )

        # Grant specific items → create in room, then _take_item runs on_take
        # (currency items destroy themselves + credit balance, normal items pick up)
        for entity_id in effects.grants:
            granted = await EntityInstance.create(
                self._pool, entity_id, room_id=self.user.current_room
            )
            if granted is None:
                logger.warning("Grant failed: entity_id %r not found", entity_id)
                continue
            await self._take_item(granted)

        # Grant random items by tag → create in room, then _take_item
        for tag in effects.grant_randoms:
            resolved = await ResolvedEntity.get_weighted_random_by_tag(self._pool, tag)
            if resolved is None:
                logger.warning("Grant random failed: no entities for tag %r", tag)
                continue
            granted = await EntityInstance.create(
                self._pool, resolved.id, room_id=self.user.current_room
            )
            if granted is None:
                logger.warning("Grant random failed: could not create %r", resolved.id)
                continue
            await self._take_item(granted)

        return result
