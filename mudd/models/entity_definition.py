"""Entity definition model for sync operations."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import asyncpg

from mudd.models.zone import SyncStats

if TYPE_CHECKING:
    from mudd.loaders.zone_loader import EntityData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntityDefinition:
    """Entity definition (template) as stored in the entities table.

    Unlike ResolvedEntity (which resolves prototype inheritance),
    this represents the raw entity definition for sync operations.
    """

    id: str
    name: str
    prototype_id: str | None
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
    contents_visible: bool | None
    rarity: str
    tags: list[str] | None

    @classmethod
    def _validate_entities(
        cls,
        entities: list[EntityData],
        room_ids: set[str],
    ) -> None:
        """Validate entity references.

        Args:
            entities: List of Entity objects from rec files
            room_ids: Set of valid room IDs

        Raises:
            ValueError: If validation fails (invalid refs, circular deps)
        """
        entity_map = {e.id: e for e in entities}
        entity_ids = set(entity_map.keys())

        # Validate prototype references
        for entity in entities:
            if entity.prototype_id and entity.prototype_id not in entity_ids:
                raise ValueError(
                    f"Entity '{entity.id}' references invalid prototype "
                    f"'{entity.prototype_id}'"
                )

        # Validate container references
        for entity in entities:
            if entity.container_id and entity.container_id not in entity_ids:
                raise ValueError(
                    f"Entity '{entity.id}' references invalid container "
                    f"'{entity.container_id}'"
                )

        # Validate room references
        for entity in entities:
            if entity.room and entity.room not in room_ids:
                raise ValueError(
                    f"Entity '{entity.id}' references invalid room '{entity.room}'"
                )

        # Check for circular prototype inheritance
        def has_prototype_cycle(entity_id: str, visited: set[str]) -> bool:
            if entity_id in visited:
                return True
            entity = entity_map.get(entity_id)
            if not entity or not entity.prototype_id:
                return False
            visited.add(entity_id)
            return has_prototype_cycle(entity.prototype_id, visited)

        for entity in entities:
            if entity.prototype_id and has_prototype_cycle(entity.id, set()):
                raise ValueError(
                    f"Circular prototype inheritance detected involving entity "
                    f"'{entity.id}'"
                )

        # Check for circular containment
        def has_containment_cycle(entity_id: str, visited: set[str]) -> bool:
            if entity_id in visited:
                return True
            entity = entity_map.get(entity_id)
            if not entity or not entity.container_id:
                return False
            visited.add(entity_id)
            return has_containment_cycle(entity.container_id, visited)

        for entity in entities:
            if entity.container_id and has_containment_cycle(entity.id, set()):
                raise ValueError(
                    f"Circular containment detected involving entity '{entity.id}'"
                )

    @classmethod
    def _topological_sort(cls, entities: list[EntityData]) -> list[EntityData]:
        """Sort entities by prototype dependency (prototypes before children).

        Args:
            entities: List of Entity objects

        Returns:
            Entities sorted by prototype_id dependency

        Raises:
            ValueError: If topological sort fails (indicates cycle)
        """
        entity_map = {e.id: e for e in entities}

        # Build dependency graph: entity -> entities that depend on it
        # An entity must be inserted BEFORE anything that references it as prototype_id
        dependents: dict[str, list[str]] = defaultdict(list)
        in_degree = {e.id: 0 for e in entities}

        for entity in entities:
            if entity.prototype_id:
                dependents[entity.prototype_id].append(entity.id)
                in_degree[entity.id] += 1

        # Start with entities that have no dependencies (no prototype)
        queue = [e.id for e in entities if in_degree[e.id] == 0]
        sorted_ids: list[str] = []

        while queue:
            entity_id = queue.pop(0)
            sorted_ids.append(entity_id)

            for dependent_id in dependents[entity_id]:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)

        # Verify all entities were sorted (defensive check)
        if len(sorted_ids) != len(entities):
            missing = set(entity_map.keys()) - set(sorted_ids)
            raise ValueError(
                f"Topological sort failed to order all entities. "
                f"This indicates a dependency cycle involving: {missing}"
            )

        return [entity_map[entity_id] for entity_id in sorted_ids]

    @classmethod
    async def _sync_entity_tags(
        cls,
        conn: asyncpg.Connection,
        entities: list[EntityData],
    ) -> int:
        """Sync entity tags to database.

        Deletes all existing tags for these entities and inserts current tags.

        Args:
            conn: Database connection (in transaction)
            entities: List of entities with tags

        Returns:
            Number of tags synced
        """
        # Collect all (entity_id, tag) pairs
        tag_pairs: list[tuple[str, str]] = []
        for entity in entities:
            if entity.tags:
                for tag in entity.tags:
                    tag_pairs.append((entity.id, tag))

        # Delete all tags for these entities (clean slate)
        entity_ids = [e.id for e in entities]
        await conn.execute(
            "DELETE FROM entity_tags WHERE entity_id = ANY($1::text[])",
            entity_ids,
        )

        # Insert current tags
        if tag_pairs:
            await conn.executemany(
                "INSERT INTO entity_tags (entity_id, tag) VALUES ($1, $2)",
                tag_pairs,
            )
            logger.info(f"Synced {len(tag_pairs)} entity tags")

        return len(tag_pairs)

    @classmethod
    async def sync_all(
        cls,
        pool: asyncpg.Pool,
        entities: list[EntityData],
        room_ids: set[str],
    ) -> SyncStats:
        """Bulk sync entity definitions. Validates, sorts, and upserts.

        Handles:
        - Validation (prototype refs, room refs, circular deps)
        - Topological sorting by prototype_id
        - Delete stale definitions
        - Upsert all definitions
        - Sync entity tags

        Args:
            pool: Database connection pool
            entities: List of Entity data from rec files
            room_ids: Set of valid room IDs for validation

        Returns:
            SyncStats with counts of synced and deleted definitions

        Raises:
            ValueError: If validation fails
        """
        if not entities:
            logger.warning("No entities found - deleting all entities")
            async with pool.acquire() as conn:
                result = await conn.execute("DELETE FROM entities")
                deleted = 0
                if result.startswith("DELETE "):
                    deleted = int(result.split()[1])
            return SyncStats(synced=0, deleted=deleted)

        # Validate references
        cls._validate_entities(entities, room_ids)

        # Topologically sort by prototype dependency
        sorted_entities = cls._topological_sort(entities)

        all_entity_ids = [e.id for e in sorted_entities]
        deleted = 0

        async with pool.acquire() as conn, conn.transaction():
            # Delete entities not in current files (CASCADE deletes instances)
            result = await conn.execute(
                "DELETE FROM entities WHERE id != ALL($1::text[])",
                all_entity_ids,
            )
            if result.startswith("DELETE "):
                deleted = int(result.split()[1])
                if deleted > 0:
                    logger.info(f"Removed {deleted} stale entities")

            # Upsert all entities in topological order
            for entity in sorted_entities:
                await conn.execute(
                    """INSERT INTO entities (
                        id, name, prototype_id,
                        description_short, description_long,
                        on_look, on_touch, on_attack, on_use, on_take,
                        on_open, on_close, on_drop, on_fish,
                        contents_visible, rarity
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                              $13, $14, $15, $16::rarity)
                    ON CONFLICT (id) DO UPDATE SET
                        name = $2,
                        prototype_id = $3,
                        description_short = $4,
                        description_long = $5,
                        on_look = $6,
                        on_touch = $7,
                        on_attack = $8,
                        on_use = $9,
                        on_take = $10,
                        on_open = $11,
                        on_close = $12,
                        on_drop = $13,
                        on_fish = $14,
                        contents_visible = $15,
                        rarity = $16::rarity
                    """,
                    entity.id,
                    entity.name,
                    entity.prototype_id,
                    entity.description_short,
                    entity.description_long,
                    entity.on_look,
                    entity.on_touch,
                    entity.on_attack,
                    entity.on_use,
                    entity.on_take,
                    entity.on_open,
                    entity.on_close,
                    entity.on_drop,
                    entity.on_fish,
                    entity.contents_visible,
                    entity.rarity,
                )

            # Sync entity tags
            await cls._sync_entity_tags(conn, sorted_entities)

        logger.info(f"Synced {len(sorted_entities)} entity definitions to database")
        return SyncStats(synced=len(sorted_entities), deleted=deleted)
