"""Entity service for runtime entity lookups with caching."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

SpawnMode = Literal["none", "move", "clone"]


FocusMode = Literal["none", "container"]


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
    contents_visible: bool | None
    focus_mode: FocusMode
    spawn_mode: SpawnMode


@dataclass(frozen=True)
class EntityInstance:
    """Entity instance with location and resolved properties."""

    instance_id: UUID
    entity: ResolvedEntity
    room: str | None
    owner_id: int | None


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
            contents_visible=row["contents_visible"],
            focus_mode=row["focus_mode"],
            spawn_mode=row["spawn_mode"],
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
                SELECT ei.id AS instance_id, ei.room, ei.owner_id, r.*
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
                SELECT ei.id AS instance_id, ei.room, ei.owner_id, r.*
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
                SELECT ei.id AS instance_id, ei.room, ei.owner_id, r.*
                FROM entity_instances ei
                CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
                JOIN entities e ON e.id = ei.entity_id
                WHERE ei.room = $1
                  AND e.container_id IS NULL
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
                SELECT ei.id AS instance_id, ei.room, ei.owner_id, r.*
                FROM entity_instances ei
                CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
                WHERE ei.room = $1
                  AND ei.entity_id IN (
                      SELECT id FROM entities WHERE container_id = $2
                  )
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

    def invalidate_cache(self) -> None:
        """Clear entity resolution cache.

        Called after entity sync to ensure cache reflects latest data.
        """
        self._entity_cache.clear()
        logger.debug("Entity cache invalidated")
