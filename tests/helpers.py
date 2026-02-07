"""Test utilities for integration tests."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import asyncpg

from mudd.cogs.shared import autocomplete_entities, resolve_entity
from mudd.commands import ActionCommand
from mudd.events.types import GameEvent
from mudd.models import EntityInstance, EntityModal, Room, RoomEntityInstance, User
from mudd.observers import EffectsObserver
from mudd.scene import Scene


@dataclass
class NullReconciler:
    """Test double for DiscordReconciler. Satisfies Observer protocol."""

    events: list[GameEvent] = field(default_factory=list)

    def notify(self, event: GameEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        pass


@dataclass(frozen=True, slots=True)
class ActResult:
    """Result from act() helper."""

    output: str
    effects: EffectsObserver
    reconciler: NullReconciler


async def _build_scene(pool: asyncpg.Pool, user_id: int) -> Scene:
    """Build a Scene from database state (no Discord dependency).

    Mirrors Scene.from_interaction() but skips InventoryThread
    (which requires a Discord thread context).
    """
    user = await User.get(pool, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")

    focus = await user.get_focus()
    if focus:
        room: Room | EntityModal = EntityModal(
            _pool=pool,
            id=f"Focus:{focus.current_container.instance_id}",
            zone_id="Focus",
            entity_instance=focus.current_container,
            is_container=True,
        )
    else:
        room = await Room.get(pool, user.current_room)
        if room is None:
            raise ValueError(f"Room {user.current_room} not found")

    return Scene(user=user, room=room, _pool=pool)


async def act(
    pool: asyncpg.Pool,
    user_id: int,
    command: ActionCommand,
    entity_query: str,
) -> ActResult:
    """Execute one game interaction. Fresh scene per call."""
    scene = await _build_scene(pool, user_id)

    effects = EffectsObserver()
    reconciler = NullReconciler()
    scene = scene.with_observers(effects, reconciler)

    entity = await resolve_entity(pool, scene, entity_query)
    if entity is None:
        raise ValueError(f"Could not resolve entity: {entity_query!r}")

    result = await scene.execute(command, entity)
    await scene.flush_observers()

    return ActResult(output=result.output, effects=effects, reconciler=reconciler)


async def autocomplete(
    pool: asyncpg.Pool,
    user_id: int,
    query: str = "",
) -> list[EntityInstance | RoomEntityInstance]:
    """Execute one autocomplete request. Fresh scene per call."""
    scene = await _build_scene(pool, user_id)
    return await autocomplete_entities(scene, query)


async def create_test_user(
    pool: asyncpg.Pool,
    user_id: int | None = None,
    room_id: str | None = None,
) -> User:
    """Create a test user in the specified room (or default room)."""
    if user_id is None:
        user_id = random.randint(100_000, 999_999)

    if room_id is None:
        default_room = await Room.get_default(pool)
        if default_room is None:
            raise ValueError("No default room configured")
        room_id = default_room.id

    await User.create_if_not_exists(pool, user_id, room_id)
    user = await User.get(pool, user_id)
    if user is None:
        raise ValueError(f"Failed to create user {user_id}")
    return user
