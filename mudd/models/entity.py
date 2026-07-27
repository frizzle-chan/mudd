"""Entity models with database access methods."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Self
from uuid import UUID

import asyncpg

from mudd.events import (
    EntityDestroyedEvent,
    EntityDroppedEvent,
    EntityPickedUpEvent,
)
from mudd.models.zone import SyncStats
from mudd.utils.random import weighted_choice
from mudd.utils.text import Rarity

if TYPE_CHECKING:
    from mudd.events import Observer
    from mudd.models.interfaces import IRoom, IUser

logger = logging.getLogger(__name__)

_ENTITY_INSTANCE_SELECT = """\
SELECT ei.id AS instance_id, ei.room, ei.owner_id,
       ei.container_entity_id, r.*
FROM entity_instances ei
CROSS JOIN LATERAL resolve_entity(ei.entity_id) r"""


@dataclass(frozen=True)
class ResolvedEntity:
    """Entity with all inherited properties resolved.

    This is a standalone model that mirrors the existing ResolvedEntity
    in mudd/services/entity.py but adds classmethods for database access.
    """

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
    on_fish: str | None
    contents_visible: bool
    rarity: Rarity

    @property
    def is_searchable(self) -> bool:
        """Whether this entity is a searchable container.

        A searchable container has hidden contents (contents_visible=False)
        and sets focus when opened (effects.set_focus in on_open).
        """
        return (
            not self.contents_visible
            and self.on_open is not None
            and "effects.set_focus" in self.on_open
        )

    @property
    def is_shop(self) -> bool:
        """Whether this entity opens a trading session when used."""
        return self.on_use is not None and "effects.shop(" in self.on_use

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> ResolvedEntity:
        """Construct ResolvedEntity from asyncpg.Record."""
        contents_visible = row["contents_visible"]
        if contents_visible is None:
            contents_visible = False  # Default to False if NULL in DB
        contents_visible = bool(contents_visible)

        return cls(
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
            on_fish=row["on_fish"],
            contents_visible=contents_visible,
            rarity=Rarity(row["rarity"]),
        )

    @classmethod
    async def get(cls, pool: asyncpg.Pool, entity_id: str) -> ResolvedEntity | None:
        """Get resolved entity by ID using prototype inheritance.

        Args:
            pool: Database connection pool
            entity_id: The entity ID to look up

        Returns:
            ResolvedEntity with inherited properties, or None if not found
        """
        row = await pool.fetchrow("SELECT * FROM resolve_entity($1)", entity_id)

        if row is None or row["name"] is None:
            return None

        return cls._from_row(row)

    @classmethod
    async def get_weighted_random_by_tag(
        cls,
        pool: asyncpg.Pool,
        tag: str,
        exclude_ids: set[str] | None = None,
    ) -> ResolvedEntity | None:
        """Select random entity by tag with weighted rarity.

        Queries entities matching the tag (excluding 'none' rarity),
        optionally filters out exclude_ids, does weighted random selection.

        Args:
            pool: Database connection pool
            tag: Tag to filter entities by
            exclude_ids: Entity IDs to exclude (for no_duplicates pools)

        Returns:
            ResolvedEntity with weighted random selection, or None if no matches
        """
        candidates = await pool.fetch(
            """
            SELECT DISTINCT e.id, e.rarity
            FROM entities e
            JOIN entity_tags et ON e.id = et.entity_id
            WHERE et.tag = $1 AND e.rarity != 'none'
            """,
            tag,
        )

        if not candidates:
            return None

        # Filter out excluded entity IDs
        if exclude_ids:
            candidates = [c for c in candidates if c["id"] not in exclude_ids]

        if not candidates:
            return None

        items = [
            (candidate["id"], Rarity(candidate["rarity"]).spawn_weight)
            for candidate in candidates
        ]

        selected_id = weighted_choice(items)
        if selected_id is None:
            return None

        return await cls.get(pool, selected_id)


@dataclass(frozen=True, slots=True)
class InstanceThreadInfo:
    """Lightweight projection of instance thread metadata.

    Used by inventory sync to reconcile Discord threads without loading
    full EntityInstance objects.
    """

    instance_id: UUID
    entity_id: str
    thread_id: int | None
    msg_id: int | None


@dataclass(frozen=True, slots=True)
class ThreadEntityInfo:
    """Entity instance paired with its Discord thread ID.

    Used by the autocomplete cache to build thread-keyed choice lists
    without loading full EntityInstance objects.
    """

    thread_id: int
    entity: EntityInstance


@dataclass(frozen=True)
class EntityInstance:
    """Entity instance with location, resolved properties, and mutation methods.

    Instances are immutable. Mutation methods (move_to_inventory, drop_to_room,
    destroy) update the database and return new instances.
    """

    instance_id: UUID
    entity: ResolvedEntity
    room_id: str | None
    owner_id: int | None
    container_entity_id: str | None = None
    _pool: asyncpg.Pool = field(repr=False, compare=False, default=None)  # ty: ignore[invalid-assignment]
    _observers: tuple[Observer, ...] = field(
        repr=False, compare=False, default_factory=tuple
    )

    def __str__(self) -> str:
        return self.entity.name

    # Proxy properties delegating to self.entity for template access
    @property
    def id(self) -> str:
        """Entity definition ID."""
        return self.entity.id

    @property
    def name(self) -> str:
        """Entity name."""
        return self.entity.name

    @property
    def description_short(self) -> str | None:
        """Short description template."""
        return self.entity.description_short

    @property
    def description_long(self) -> str | None:
        """Long description template."""
        return self.entity.description_long

    @property
    def contents_visible(self) -> bool:
        """Whether container contents are visible."""
        return self.entity.contents_visible

    @property
    def rarity(self) -> Rarity:
        """Item rarity tier."""
        return self.entity.rarity

    @property
    def room(self) -> str | None:
        """Alias for room_id for backward compatibility."""
        return self.room_id

    # Capability properties - real entities support all operations
    @property
    def is_focusable(self) -> bool:
        return True

    @property
    def can_pickup(self) -> bool:
        return True

    @property
    def can_drop(self) -> bool:
        return True

    @property
    def can_destroy(self) -> bool:
        return True

    def with_observers(self, *observers: Observer) -> Self:
        """Return a new instance with additional observers appended.

        Args:
            *observers: Observer callbacks to add

        Returns:
            New EntityInstance with observers appended
        """
        return replace(self, _observers=self._observers + observers)

    @classmethod
    def _from_row(
        cls,
        row: asyncpg.Record,
        entity: ResolvedEntity,
        pool: asyncpg.Pool,
        observers: tuple[Observer, ...] = (),
    ) -> EntityInstance:
        """Construct EntityInstance from asyncpg.Record."""
        ei = cls(
            instance_id=row["instance_id"],
            entity=entity,
            room_id=row["room"],
            owner_id=row["owner_id"],
            container_entity_id=row["container_entity_id"],
            _pool=pool,
            _observers=observers,
        )
        return ei

    @classmethod
    async def get(cls, pool: asyncpg.Pool, instance_id: UUID) -> EntityInstance | None:
        """Get entity instance by UUID.

        Args:
            pool: Database connection pool
            instance_id: The instance UUID

        Returns:
            EntityInstance with resolved entity, or None if not found
        """
        row = await pool.fetchrow(
            f"{_ENTITY_INSTANCE_SELECT}\nWHERE ei.id = $1",
            instance_id,
        )

        if row is None:
            return None

        entity = ResolvedEntity._from_row(row)
        return cls._from_row(row, entity, pool)

    @classmethod
    async def get_by_room(cls, pool: asyncpg.Pool, room: IRoom) -> list[EntityInstance]:
        """Get all entity instances in a room.

        Args:
            pool: Database connection pool
            room: Room model instance

        Returns:
            List of EntityInstance objects in the room
        """
        rows = await pool.fetch(
            f"{_ENTITY_INSTANCE_SELECT}\nWHERE ei.room = $1",
            room.id,
        )

        instances = []
        for row in rows:
            entity = ResolvedEntity._from_row(row)
            instances.append(cls._from_row(row, entity, pool))
        return instances

    @classmethod
    async def get_by_inventory_thread_id(
        cls, pool: asyncpg.Pool, thread_id: int
    ) -> EntityInstance | None:
        async with pool.acquire() as conn:
            instance_row = await conn.fetchrow(
                """
                SELECT ei.id AS instance_id, ei.room, ei.owner_id,
                    ei.container_entity_id, ei.entity_id
                FROM entity_instances ei
                WHERE ei.discord_thread_id = $1
                """,
                thread_id,
            )
            if not instance_row:
                return None

            # TODO: cache this, it's static for all callers
            entity_row = await conn.fetchrow(
                """
                SELECT * FROM resolve_entity($1)
                """,
                instance_row["entity_id"],
            )

        entity = ResolvedEntity._from_row(entity_row)
        return cls._from_row(instance_row, entity, pool)

    @classmethod
    async def get_all_with_threads(cls, pool: asyncpg.Pool) -> list[ThreadEntityInfo]:
        """Get all entity instances that have a Discord thread ID.

        Returns lightweight ThreadEntityInfo projections for cache building.
        """
        rows = await pool.fetch(
            """
            SELECT ei.id AS instance_id, ei.room, ei.owner_id,
                   ei.container_entity_id, ei.discord_thread_id, r.*
            FROM entity_instances ei
            CROSS JOIN LATERAL resolve_entity(ei.entity_id) r
            WHERE ei.discord_thread_id IS NOT NULL
            """,
        )

        results: list[ThreadEntityInfo] = []
        for row in rows:
            entity = ResolvedEntity._from_row(row)
            instance = cls._from_row(row, entity, pool)
            results.append(
                ThreadEntityInfo(
                    thread_id=row["discord_thread_id"],
                    entity=instance,
                )
            )
        return results

    @classmethod
    async def get_by_owner(
        cls, pool: asyncpg.Pool, owner_id: int
    ) -> list[EntityInstance]:
        """Get all entity instances owned by a user (inventory).

        Args:
            pool: Database connection pool
            owner_id: Discord user ID

        Returns:
            List of EntityInstance objects in the user's inventory
        """
        rows = await pool.fetch(
            f"{_ENTITY_INSTANCE_SELECT}\nWHERE ei.owner_id = $1",
            owner_id,
        )

        instances = []
        for row in rows:
            entity = ResolvedEntity._from_row(row)
            instances.append(cls._from_row(row, entity, pool))
        return instances

    @classmethod
    async def get_thread_and_msg_ids(
        cls, pool: asyncpg.Pool, instance_id: UUID
    ) -> tuple[int | None, int | None]:
        """Get the Discord thread ID and description message ID for an instance.

        Args:
            pool: Database connection pool
            instance_id: Entity instance UUID

        Returns:
            Tuple of (thread_id, description_msg_id), either may be None
        """
        row = await pool.fetchrow(
            "SELECT discord_thread_id, discord_description_msg_id "
            "FROM entity_instances WHERE id = $1",
            instance_id,
        )
        if row is None:
            return (None, None)
        return (row["discord_thread_id"], row["discord_description_msg_id"])

    @classmethod
    async def get_thread_id(cls, pool: asyncpg.Pool, instance_id: UUID) -> int | None:
        """Get the Discord thread ID for an entity instance.

        Args:
            pool: Database connection pool
            instance_id: Entity instance UUID

        Returns:
            Discord thread ID, or None if no thread exists
        """
        row = await pool.fetchrow(
            "SELECT discord_thread_id FROM entity_instances WHERE id = $1",
            instance_id,
        )
        return row["discord_thread_id"] if row else None

    @classmethod
    async def get_description_msg_id(
        cls, pool: asyncpg.Pool, instance_id: UUID
    ) -> int | None:
        """Get the Discord description message ID for an entity instance.

        Args:
            pool: Database connection pool
            instance_id: Entity instance UUID

        Returns:
            Discord message ID, or None if no message exists
        """
        row = await pool.fetchrow(
            "SELECT discord_description_msg_id FROM entity_instances WHERE id = $1",
            instance_id,
        )
        return row["discord_description_msg_id"] if row else None

    @classmethod
    async def update_thread_ids(
        cls,
        pool: asyncpg.Pool,
        instance_id: UUID,
        thread_id: int,
        msg_id: int,
    ) -> None:
        """Set the Discord thread and description message IDs for an instance.

        Args:
            pool: Database connection pool
            instance_id: Entity instance UUID
            thread_id: Discord thread ID
            msg_id: Discord message ID for the description
        """
        await pool.execute(
            """UPDATE entity_instances
            SET discord_thread_id = $1, discord_description_msg_id = $2
            WHERE id = $3""",
            thread_id,
            msg_id,
            instance_id,
        )

    @classmethod
    async def claim_thread_ids(
        cls,
        pool: asyncpg.Pool,
        instance_id: UUID,
        thread_id: int,
        msg_id: int,
    ) -> bool:
        """Atomically set thread IDs only if no thread is already assigned.

        Uses a conditional UPDATE to prevent race conditions where two
        concurrent callers both create threads for the same entity instance.

        Args:
            pool: Database connection pool
            instance_id: Entity instance UUID
            thread_id: Discord thread ID to claim
            msg_id: Discord message ID for the description

        Returns:
            True if this caller won (row updated), False if another caller
            already set a thread ID.
        """
        result = await pool.execute(
            """UPDATE entity_instances
            SET discord_thread_id = $1, discord_description_msg_id = $2
            WHERE id = $3 AND discord_thread_id IS NULL""",
            thread_id,
            msg_id,
            instance_id,
        )
        return result == "UPDATE 1"

    @classmethod
    async def clear_thread_ids(cls, pool: asyncpg.Pool, instance_id: UUID) -> None:
        """Clear the Discord thread and description message IDs for an instance.

        Args:
            pool: Database connection pool
            instance_id: Entity instance UUID
        """
        await pool.execute(
            """UPDATE entity_instances
            SET discord_thread_id = NULL, discord_description_msg_id = NULL
            WHERE id = $1""",
            instance_id,
        )

    @classmethod
    async def get_thread_ids_by_owner(
        cls, pool: asyncpg.Pool, owner_id: int
    ) -> set[int]:
        """Get all Discord thread IDs for instances owned by a user.

        Args:
            pool: Database connection pool
            owner_id: Discord user ID

        Returns:
            Set of Discord thread IDs (excludes NULL values)
        """
        rows = await pool.fetch(
            """
            SELECT discord_thread_id FROM entity_instances
            WHERE owner_id = $1 AND discord_thread_id IS NOT NULL
            """,
            owner_id,
        )
        return {row["discord_thread_id"] for row in rows}

    @classmethod
    async def get_thread_info_by_owner(
        cls, pool: asyncpg.Pool, owner_id: int
    ) -> list[InstanceThreadInfo]:
        """Get thread metadata for all instances owned by a user.

        Args:
            pool: Database connection pool
            owner_id: Discord user ID

        Returns:
            List of InstanceThreadInfo with thread metadata
        """
        rows = await pool.fetch(
            """
            SELECT ei.id, ei.entity_id,
                   ei.discord_thread_id, ei.discord_description_msg_id
            FROM entity_instances ei
            WHERE ei.owner_id = $1
            """,
            owner_id,
        )
        return [
            InstanceThreadInfo(
                instance_id=row["id"],
                entity_id=row["entity_id"],
                thread_id=row["discord_thread_id"],
                msg_id=row["discord_description_msg_id"],
            )
            for row in rows
        ]

    @classmethod
    async def get_top_level_by_room(
        cls, pool: asyncpg.Pool, room: IRoom
    ) -> list[EntityInstance]:
        """Get top-level entities in a room (no container).

        Args:
            pool: Database connection pool
            room: Room model instance

        Returns:
            List of EntityInstance objects with no container in the room
        """
        rows = await pool.fetch(
            f"{_ENTITY_INSTANCE_SELECT}\n"
            "WHERE ei.room = $1 AND ei.container_entity_id IS NULL",
            room.id,
        )

        instances = []
        for row in rows:
            entity = ResolvedEntity._from_row(row)
            instances.append(cls._from_row(row, entity, pool))
        return instances

    @classmethod
    async def create(
        cls,
        pool: asyncpg.Pool,
        entity_id: str,
        *,
        room: IRoom | None = None,
        room_id: str | None = None,
        owner_id: int | None = None,
        container_entity_id: str | None = None,
        spawning_pool_id: str | None = None,
    ) -> EntityInstance | None:
        """Create a new entity instance.

        Args:
            pool: Database connection pool
            entity_id: Entity definition ID
            room: Room to place the instance (mutually exclusive with owner_id)
            room_id: Alternative to room object - room ID string
            owner_id: Owner's Discord ID for inventory (mutually exclusive with room)
            container_entity_id: Optional container entity ID
            spawning_pool_id: Optional spawning pool ID for spawned instances

        Returns:
            New EntityInstance, or None if entity_id is invalid
        """
        entity = await ResolvedEntity.get(pool, entity_id)
        if entity is None:
            return None

        resolved_room_id = room.id if room else room_id
        row = await pool.fetchrow(
            """
            INSERT INTO entity_instances
                (entity_id, room, owner_id, container_entity_id, spawning_pool_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id AS instance_id, room, owner_id, container_entity_id
            """,
            entity_id,
            resolved_room_id,
            owner_id,
            container_entity_id,
            spawning_pool_id,
        )

        if row is None:
            return None

        return cls(
            instance_id=row["instance_id"],
            entity=entity,
            room_id=row["room"],
            owner_id=row["owner_id"],
            container_entity_id=row["container_entity_id"],
            _pool=pool,
        )

    @classmethod
    async def sync_world_instances(
        cls,
        pool: asyncpg.Pool,
        instance_data: list[tuple[str, str, str | None]],
    ) -> SyncStats:
        """Sync world instances from rec file data.

        Deletes stale world instances (is_world_instance=TRUE),
        upserts instances from rec file data.
        Player instances (is_world_instance=FALSE) are preserved.

        Args:
            pool: Database connection pool
            instance_data: List of (entity_id, room, container_id) tuples

        Returns:
            SyncStats with synced and deleted counts
        """
        deleted = 0
        synced = 0

        async with pool.acquire() as conn, conn.transaction():
            # Delete world instances no longer in rec files
            if instance_data:
                result = await conn.execute(
                    """DELETE FROM entity_instances
                    WHERE is_world_instance = TRUE
                      AND (entity_id, room) NOT IN (
                          SELECT * FROM unnest($1::text[], $2::text[])
                      )""",
                    [e[0] for e in instance_data],
                    [e[1] for e in instance_data],
                )
                if result.startswith("DELETE "):
                    deleted = int(result.split()[1])
            else:
                result = await conn.execute(
                    "DELETE FROM entity_instances WHERE is_world_instance = TRUE"
                )
                if result.startswith("DELETE "):
                    deleted = int(result.split()[1])

            # Upsert world instances from rec file
            if instance_data:
                await conn.executemany(
                    """INSERT INTO entity_instances
                           (entity_id, room, container_entity_id, is_world_instance)
                    VALUES ($1, $2, $3, TRUE)
                    ON CONFLICT (entity_id, room) WHERE is_world_instance = TRUE
                    DO UPDATE SET container_entity_id = $3""",
                    instance_data,
                )
                synced = len(instance_data)
                logger.info(f"Ensured {synced} entity instances exist")

        return SyncStats(synced=synced, deleted=deleted)

    async def move_to_inventory(self, user: IUser) -> EntityInstance:
        """Move this instance to a user's inventory.

        Updates the database and notifies observers with "picked_up" event.

        Args:
            user: User model instance to receive the item

        Returns:
            New EntityInstance with updated location
        """
        await self._pool.execute(
            """
            WITH reset AS (
                UPDATE spawning_pools SET last_spawn_at = NOW()
                WHERE id = (SELECT spawning_pool_id FROM entity_instances WHERE id = $1)
            )
            UPDATE entity_instances
            SET room = NULL, owner_id = $2, container_entity_id = NULL,
                spawning_pool_id = NULL
            WHERE id = $1
            """,
            self.instance_id,
            user.id,
        )

        new_instance = replace(
            self,
            room_id=None,
            owner_id=user.id,
            container_entity_id=None,
        )
        for observer in new_instance._observers:
            observer.notify(EntityPickedUpEvent(instance=new_instance))
        return new_instance

    async def detach_from_inventory(self) -> EntityInstance:
        """Remove this instance from a user's inventory without placing it anywhere.

        Used when selling an item to a shop. Sets room, owner_id, and
        container_entity_id to NULL. Emits EntityDroppedEvent so the
        InventoryReconciler cleans up the Discord thread.

        Returns:
            New EntityInstance with cleared location fields
        """
        await self._pool.execute(
            """
            UPDATE entity_instances
            SET room = NULL, owner_id = NULL, container_entity_id = NULL
            WHERE id = $1
            """,
            self.instance_id,
        )

        new_instance = replace(
            self,
            room_id=None,
            owner_id=None,
            container_entity_id=None,
        )
        for observer in new_instance._observers:
            observer.notify(EntityDroppedEvent(instance=new_instance))
        return new_instance

    async def drop_to_room(
        self,
        room: IRoom,
        container: EntityInstance | None = None,
    ) -> EntityInstance:
        """Drop this instance to a room, optionally into a container.

        Updates the database and notifies observers with "dropped" event.

        Args:
            room: Room model instance to drop into
            container: Optional container EntityInstance

        Returns:
            New EntityInstance with updated location
        """
        container_id = container.entity.id if container else None
        await self._pool.execute(
            """
            UPDATE entity_instances
            SET room = $2, owner_id = NULL, container_entity_id = $3
            WHERE id = $1
            """,
            self.instance_id,
            room.id,
            container_id,
        )

        new_instance = replace(
            self,
            room_id=room.id,
            owner_id=None,
            container_entity_id=container_id,
        )
        for observer in new_instance._observers:
            observer.notify(EntityDroppedEvent(instance=new_instance))
        return new_instance

    async def destroy(self) -> None:
        """Delete this instance from the database.

        Notifies observers with "destroyed" event before deletion.
        Pre-fetches thread_id so observers can clean up Discord threads
        after the row is deleted.
        """
        thread_id = await EntityInstance.get_thread_id(self._pool, self.instance_id)
        for observer in self._observers:
            observer.notify(EntityDestroyedEvent(instance=self, thread_id=thread_id))
        await self._pool.execute(
            """
            WITH reset AS (
                UPDATE spawning_pools SET last_spawn_at = NOW()
                WHERE id = (SELECT spawning_pool_id FROM entity_instances WHERE id = $1)
            )
            DELETE FROM entity_instances WHERE id = $1
            """,
            self.instance_id,
        )

    async def get_container(self) -> EntityInstance | None:
        """Get the container EntityInstance if this entity is inside one.

        Returns:
            Container EntityInstance, or None if not in a container
        """
        if self.container_entity_id is None:
            return None

        return await EntityInstance.get(self._pool, UUID(self.container_entity_id))

    async def get_contents(self) -> list[EntityInstance]:
        """Get direct children of this container entity.

        Returns:
            List of EntityInstance objects contained in this entity
        """
        if self.room_id is None:
            return []

        rows = await self._pool.fetch(
            f"{_ENTITY_INSTANCE_SELECT}\n"
            "WHERE ei.room = $1 AND ei.container_entity_id = $2",
            self.room_id,
            self.entity.id,
        )

        instances = []
        for row in rows:
            entity = ResolvedEntity._from_row(row)
            instances.append(
                EntityInstance._from_row(row, entity, self._pool, self._observers)
            )
        return instances
