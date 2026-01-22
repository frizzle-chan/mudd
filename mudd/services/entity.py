"""Entity service for runtime entity lookups with caching."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import asyncpg

from mudd.utils.random import weighted_choice

logger = logging.getLogger(__name__)

SpawnMode = Literal["none", "move", "clone"]

FocusMode = Literal["none", "container"]

Rarity = Literal["common", "uncommon", "rare", "epic", "legendary", "mythic", "quest"]

# Rarity emoji for display names
RARITY_EMOJI: dict[Rarity, str] = {
    "common": "\u26aa",  # White circle
    "uncommon": "\U0001f7e2",  # Green circle
    "rare": "\U0001f535",  # Blue circle
    "epic": "\U0001f7e3",  # Purple circle
    "legendary": "\U0001f7e0",  # Orange circle
    "mythic": "\u3299\ufe0f",  # Japanese "secret" symbol
    "quest": "\U0001f537",  # Blue diamond
}

# Rarity weights for spawning (sum to 1000)
RARITY_WEIGHTS: dict[Rarity, int] = {
    "common": 600,
    "uncommon": 250,
    "rare": 100,
    "epic": 40,
    "legendary": 9,
    "mythic": 1,
    "quest": 0,  # Never spawns from pools
}


@dataclass(frozen=True)
class ResolvedEntity:
    """Entity with all inherited properties resolved."""

    id: str
    name: str
    description_short: str | None
    description_long: str | None
    on_look: str | None
    on_touch: str | None
    on_attack: str | None
    on_use: str | None
    on_take: str | None
    on_open: str | None
    on_close: str | None
    on_drop: str | None
    contents_visible: bool | None
    focus_mode: FocusMode
    spawn_mode: SpawnMode
    rarity: Rarity

    @property
    def display_name(self) -> str:
        """Name with rarity emoji suffix for display."""
        return f"{self.name} {RARITY_EMOJI[self.rarity]}"


@dataclass(frozen=True)
class EntityInstance:
    """Entity instance with location and resolved properties."""

    instance_id: UUID
    entity: ResolvedEntity
    room: str | None
    owner_id: int | None
    container_entity_id: str | None = None


class EntityService:
    """Manages entity data access with in-memory caching.

    Caches resolved entity definitions to avoid repeated database queries.
    Cache is invalidated when entities are synced.

    Usage:
        service = EntityService(pool)
        entity = await service.get_entity("foyer_table")
        room_entities = await service.get_room_entities("foyer")
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._entity_cache: dict[str, ResolvedEntity] = {}

    def _entity_from_row(self, row: asyncpg.Record) -> ResolvedEntity:
        """Construct ResolvedEntity from database row."""
        return ResolvedEntity(
            id=row["id"],
            name=row["name"],
            description_short=row["description_short"],
            description_long=row["description_long"],
            on_look=row["on_look"],
            on_touch=row["on_touch"],
            on_attack=row["on_attack"],
            on_use=row["on_use"],
            on_take=row["on_take"],
            on_open=row["on_open"],
            on_close=row["on_close"],
            on_drop=row["on_drop"],
            contents_visible=row["contents_visible"],
            focus_mode=row["focus_mode"],
            spawn_mode=row["spawn_mode"],
            rarity=row["rarity"],
        )

    async def get_entity(self, entity_id: str) -> ResolvedEntity | None:
        """Get resolved entity by ID, using cache when available.

        Args:
            entity_id: The entity ID to look up

        Returns:
            ResolvedEntity with inherited properties, or None if not found
        """
        if entity_id in self._entity_cache:
            return self._entity_cache[entity_id]

        try:
            row = await self._pool.fetchrow(
                "SELECT * FROM resolve_entity($1)", entity_id
            )
        except Exception:
            logger.exception("Database error fetching entity '%s'", entity_id)
            raise

        if row is None:
            return None

        if row["name"] is None:
            logger.warning("Entity '%s' has null name after resolution", entity_id)
            return None

        entity = self._entity_from_row(row)
        self._entity_cache[entity_id] = entity
        return entity

    async def get_room_entities(self, room: str) -> list[EntityInstance]:
        """Get all entity instances in a room with resolved properties.

        Args:
            room: Room ID

        Returns:
            List of EntityInstance objects in the room
        """
        try:
            rows = await self._pool.fetch(
                """
                SELECT ei.id AS instance_id, ei.room, ei.owner_id,
                       ei.container_entity_id, r.*
                FROM entity_instances ei
                CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
                WHERE ei.room = $1
                """,
                room,
            )
        except Exception:
            logger.exception("Database error fetching entities in room '%s'", room)
            raise

        instances = []
        for row in rows:
            entity = self._entity_from_row(row)
            self._entity_cache[entity.id] = entity
            instances.append(
                EntityInstance(
                    instance_id=row["instance_id"],
                    entity=entity,
                    room=row["room"],
                    owner_id=row["owner_id"],
                    container_entity_id=row["container_entity_id"],
                )
            )

        return instances

    async def get_entity_instance(self, instance_id: UUID) -> EntityInstance | None:
        """Get a specific entity instance by its UUID.

        Args:
            instance_id: The instance UUID

        Returns:
            EntityInstance with resolved entity, or None if not found
        """
        try:
            row = await self._pool.fetchrow(
                """
                SELECT ei.id AS instance_id, ei.room, ei.owner_id,
                       ei.container_entity_id, r.*
                FROM entity_instances ei
                CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
                WHERE ei.id = $1
                """,
                instance_id,
            )
        except Exception:
            logger.exception(
                "Database error fetching entity instance '%s'", instance_id
            )
            raise

        if row is None:
            return None

        entity = self._entity_from_row(row)
        self._entity_cache[entity.id] = entity

        return EntityInstance(
            instance_id=row["instance_id"],
            entity=entity,
            room=row["room"],
            owner_id=row["owner_id"],
            container_entity_id=row["container_entity_id"],
        )

    async def get_top_level_room_entities(self, room: str) -> list[EntityInstance]:
        """Get entity instances in a room that are not contained in another entity.

        Args:
            room: Room ID

        Returns:
            List of EntityInstance objects that are top-level (no container)
        """
        try:
            rows = await self._pool.fetch(
                """
                SELECT ei.id AS instance_id, ei.room, ei.owner_id,
                       ei.container_entity_id, r.*
                FROM entity_instances ei
                CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
                WHERE ei.room = $1
                  AND ei.container_entity_id IS NULL
                """,
                room,
            )
        except Exception:
            logger.exception(
                "Database error fetching top-level entities in room '%s'", room
            )
            raise

        instances = []
        for row in rows:
            entity = self._entity_from_row(row)
            self._entity_cache[entity.id] = entity
            instances.append(
                EntityInstance(
                    instance_id=row["instance_id"],
                    entity=entity,
                    room=row["room"],
                    owner_id=row["owner_id"],
                    container_entity_id=row["container_entity_id"],
                )
            )

        return instances

    async def get_container_contents(
        self, container_id: str, room: str
    ) -> list[EntityInstance]:
        """Get direct children of a container entity in a specific room.

        Args:
            container_id: The container entity ID
            room: Room ID to search in

        Returns:
            List of EntityInstance objects contained in the entity
        """
        try:
            rows = await self._pool.fetch(
                """
                SELECT ei.id AS instance_id, ei.room, ei.owner_id,
                       ei.container_entity_id, r.*
                FROM entity_instances ei
                CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
                WHERE ei.room = $1
                  AND ei.container_entity_id = $2
                """,
                room,
                container_id,
            )
        except Exception:
            logger.exception(
                "Database error fetching contents of '%s' in room '%s'",
                container_id,
                room,
            )
            raise

        instances = []
        for row in rows:
            entity = self._entity_from_row(row)
            self._entity_cache[entity.id] = entity
            instances.append(
                EntityInstance(
                    instance_id=row["instance_id"],
                    entity=entity,
                    room=row["room"],
                    owner_id=row["owner_id"],
                    container_entity_id=row["container_entity_id"],
                )
            )

        return instances

    async def get_visible_entities(self, room: str) -> list[EntityInstance]:
        """Get visible entities for a room.

        Returns top-level entities + contents of visible containers.
        Not cached here - PlayerContextService caches the processed results.

        Args:
            room: Room ID

        Returns:
            List of EntityInstance objects visible in the room
        """
        top_level = await self.get_top_level_room_entities(room)
        result: list[EntityInstance] = []

        for instance in top_level:
            result.append(instance)
            # Add contents of visible containers
            if instance.entity.contents_visible:
                contents = await self.get_container_contents(instance.entity.id, room)
                result.extend(contents)

        return result

    async def get_user_inventory(self, user_id: int) -> list[EntityInstance]:
        """Get all entity instances owned by a user.

        Args:
            user_id: Discord user ID

        Returns:
            List of EntityInstance objects in the user's inventory
        """
        try:
            rows = await self._pool.fetch(
                """
                SELECT ei.id AS instance_id, ei.room, ei.owner_id,
                       ei.container_entity_id, r.*
                FROM entity_instances ei
                CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
                WHERE ei.owner_id = $1
                """,
                user_id,
            )
        except Exception:
            logger.exception("Database error fetching inventory for user '%s'", user_id)
            raise

        instances = []
        for row in rows:
            entity = self._entity_from_row(row)
            self._entity_cache[entity.id] = entity
            instances.append(
                EntityInstance(
                    instance_id=row["instance_id"],
                    entity=entity,
                    room=row["room"],
                    owner_id=row["owner_id"],
                    container_entity_id=row["container_entity_id"],
                )
            )

        return instances

    async def get_random_entity_by_tag(self, tag: str) -> ResolvedEntity | None:
        """Select random entity by tag with weighted rarity.

        Queries entities matching the tag (excluding quest rarity),
        does weighted random selection based on RARITY_WEIGHTS.

        Args:
            tag: Tag to filter entities by

        Returns:
            ResolvedEntity with weighted random selection, or None if no matches
        """
        candidates = await self._pool.fetch(
            """
            SELECT DISTINCT e.id, e.rarity
            FROM entities e
            JOIN entity_tags et ON e.id = et.entity_id
            WHERE et.tag = $1 AND e.rarity != 'quest'
            """,
            tag,
        )

        if not candidates:
            return None

        items = [
            (candidate["id"], RARITY_WEIGHTS.get(candidate["rarity"], 0))
            for candidate in candidates
        ]

        selected_id = weighted_choice(items)
        if selected_id is None:
            return None

        return await self.get_entity(selected_id)

    def invalidate_cache(self) -> None:
        """Clear entity resolution cache.

        Called after entity sync to ensure cache reflects latest data.
        """
        self._entity_cache.clear()
        logger.debug("Entity cache invalidated")
