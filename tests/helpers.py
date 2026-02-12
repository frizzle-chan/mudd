"""Test utilities for integration tests."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from uuid import UUID

import asyncpg

from mudd.caches.entity_autocomplete import EntityAutocompleteCache
from mudd.caches.user import UserCache
from mudd.cogs.shared import (
    entity_instance_id_autocomplete as _entity_instance_id_autocomplete,
)
from mudd.cogs.shared import (
    resolve_entity,
)
from mudd.commands import ActionCommand
from mudd.events import Observer
from mudd.events.types import GameEvent
from mudd.models import EntityInstance, Room, RoomEntityInstance, User
from mudd.observers import EffectsObserver, flush_all
from mudd.observers.skills import SkillsObserver
from mudd.observers.spawning_pool import SpawningPoolObserver
from mudd.scene import Scene

# Module-level cache holders, wired by the session-scoped autouse fixture
# in tests/conftest.py.
entity_cache: EntityAutocompleteCache | None = None
user_cache: UserCache | None = None


@dataclass
class NullReconciler:
    """Test double for DiscordReconciler. Satisfies Observer protocol."""

    flush_priority: int = 0
    events: list[GameEvent] = field(default_factory=list)

    def notify(self, event: GameEvent) -> None:
        self.events.append(event)

    async def flush(self) -> list[GameEvent]:
        return []

    async def post_flush(self) -> None:
        pass


@dataclass(frozen=True, slots=True)
class ActResult:
    """Result from act() helper."""

    output: str
    effects: EffectsObserver
    reconciler: NullReconciler
    skills: SkillsObserver


@dataclass(frozen=True, slots=True)
class MoveResult:
    """Result from move() helper."""

    reconciler: NullReconciler
    skills: SkillsObserver


async def act(
    pool: asyncpg.Pool,
    user_id: int,
    command: ActionCommand,
    entity_query: str,
) -> ActResult:
    """Execute one game interaction. Fresh scene per call."""
    scene = await Scene.from_user(pool, user_id)

    reconciler = NullReconciler()
    spawning = SpawningPoolObserver(pool)
    skills = SkillsObserver(
        _pool=pool,
        _user_id=user_id,
        _room_id=scene.user.current_room,
    )
    extra: list[Observer] = []
    if entity_cache is not None:
        extra.append(entity_cache.create_invalidator(pool, scene.user.current_room))
    if user_cache is not None:
        extra.append(user_cache.create_invalidator(pool))
    effects = EffectsObserver(_forward_targets=(skills, reconciler, *extra))
    scene = scene.with_observers(effects, spawning, skills, reconciler, *extra)

    entity = await resolve_entity(pool, scene, entity_query)
    if entity is None:
        raise ValueError(f"Could not resolve entity: {entity_query!r}")

    result = await scene.execute(command, entity)
    await scene.flush_observers()

    return ActResult(
        output=result.output, effects=effects, reconciler=reconciler, skills=skills
    )


async def autocomplete(
    pool: asyncpg.Pool,
    user_id: int,
    query: str = "",
) -> list[EntityInstance | RoomEntityInstance]:
    """Execute one autocomplete request. Fresh scene per call.

    Delegates to the real entity_instance_id_autocomplete function,
    then resolves the returned Choice objects back to entity instances.
    """
    choices = await _entity_instance_id_autocomplete(
        pool,
        user_id,
        query,
        entity_cache=entity_cache,
        user_cache=user_cache,
    )
    return await _resolve_choices(pool, choices)


async def _resolve_choices(
    pool: asyncpg.Pool,
    choices: list,
) -> list[EntityInstance | RoomEntityInstance]:
    """Convert cached Choice[str] objects back to entity/room instances."""
    from discord import app_commands

    entities: list[EntityInstance | RoomEntityInstance] = []
    for choice in choices:
        assert isinstance(choice, app_commands.Choice)
        value: str = choice.value
        if value.startswith("entity://"):
            inst = await EntityInstance.get(pool, UUID(value[9:]))
            if inst is not None:
                entities.append(inst)
        elif value.startswith("room://"):
            room = await Room.get(pool, value[7:])
            if room is not None:
                entities.append(room.as_entity(focus_name=None))
    return entities


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

    if user_cache is not None:
        await user_cache.rebuild_user(pool, user.id)

    return user


async def move(
    pool: asyncpg.Pool,
    user_id: int,
    room_id: str,
    guild_id: int = 12345,
) -> MoveResult:
    """Move a user to a room with cache invalidation (mirrors movement cog)."""
    fresh = await User.get(pool, user_id)
    if fresh is None:
        raise ValueError(f"User {user_id} not found")

    reconciler = NullReconciler()
    skills = SkillsObserver(
        _pool=pool,
        _user_id=user_id,
        _room_id=fresh.current_room,
    )
    observers: list[Observer] = [skills, reconciler]
    if user_cache is not None:
        observers.append(user_cache.create_invalidator(pool))
    if entity_cache is not None:
        observers.append(entity_cache.create_invalidator(pool, fresh.current_room))

    user_with_obs = fresh.with_observers(*observers)
    await user_with_obs.move_to(room_id, guild_id=guild_id)
    await flush_all(observers)

    return MoveResult(reconciler=reconciler, skills=skills)
