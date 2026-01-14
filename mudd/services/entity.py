"""Entity service for runtime entity lookups with caching."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from mudd.services.database import get_pool

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

SpawnMode = Literal["none", "move", "clone"]


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
    contents_visible: bool | None
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
        service = get_entity_service()
        entity = await service.get_entity("foyer_table")
        room_entities = await service.get_room_entities("foyer")
    """

    def __init__(self) -> None:
        self._entity_cache: dict[str, ResolvedEntity] = {}

    def _entity_from_row(self, row: "asyncpg.Record") -> ResolvedEntity:
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
            contents_visible=row["contents_visible"],
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
            pool = await get_pool()
            row = await pool.fetchrow("SELECT * FROM resolve_entity($1)", entity_id)
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
            pool = await get_pool()
            rows = await pool.fetch(
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
            pool = await get_pool()
            row = await pool.fetchrow(
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
            pool = await get_pool()
            rows = await pool.fetch(
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

    def invalidate_cache(self) -> None:
        """Clear the entity cache.

        Called after entity sync to ensure cache reflects latest data.
        """
        self._entity_cache.clear()
        logger.debug("Entity cache invalidated")


# Module-level singleton
_service: EntityService | None = None


def is_entity_service_initialized() -> bool:
    """Check if the entity service has been initialized."""
    return _service is not None


def get_entity_service() -> EntityService:
    """Get the entity service singleton.

    Raises:
        RuntimeError: If service not initialized (call init_entity_service first)
    """
    if _service is None:
        raise RuntimeError("EntityService not initialized")
    return _service


def init_entity_service() -> EntityService:
    """Initialize the entity service singleton.

    Returns:
        The initialized EntityService instance
    """
    global _service
    _service = EntityService()
    logger.info("Entity service initialized")
    return _service
