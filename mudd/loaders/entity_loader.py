"""Entity loader for syncing entity definitions and instances to PostgreSQL."""

import logging
from collections import defaultdict
from pathlib import Path

import asyncpg

from mudd.loaders.zone_loader import (
    Entity,
    SpawningPool,
    load_entities_from_rec,
    load_rooms_from_rec,
    load_spawning_pools_from_rec,
)

logger = logging.getLogger(__name__)


def _validate_and_sort_entities(
    entities: list[Entity],
    room_ids: set[str],
) -> list[Entity]:
    """Validate entity references and return topologically sorted list.

    Args:
        entities: List of Entity objects from rec files
        room_ids: Set of valid room IDs

    Returns:
        Entities sorted by prototype dependency (prototypes before children)

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

    # Topological sort by prototype_id (Kahn's algorithm)
    # Build dependency graph: entity -> entities that depend on it
    # An entity must be inserted BEFORE anything that references it as prototype_id
    # Note: container_id no longer has FK on entities table (moved to instances)
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

    # Build sorted entity list
    return [entity_map[entity_id] for entity_id in sorted_ids]


async def sync_entities(pool: asyncpg.Pool, world_file: Path) -> int:
    """Sync entities from a world rec file to database with validation.

    Full sync: deletes entities not in current files, upserts all current
    entities, and creates entity_instances for entities with Room field.
    Validates references and circular dependencies before database operations.
    Topologically sorts by prototype_id and container_id to satisfy FK constraints.

    Args:
        pool: Database connection pool
        world_file: Path to the world .rec file

    Returns:
        Number of entities synced.

    Raises:
        ValueError: If validation fails (circular deps, invalid references)
    """
    entities = load_entities_from_rec(world_file)

    if not entities:
        logger.warning("No entities found in world file - deleting all entities")
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM entities")
        return 0

    # Load rooms for room reference validation
    rooms = load_rooms_from_rec(world_file)
    room_ids = {r.id for r in rooms}

    # Validate and sort entities
    sorted_entities = _validate_and_sort_entities(entities, room_ids)

    all_entity_ids = [e.id for e in sorted_entities]

    # Collect entities with Room field for instance creation
    # container_id from rec file becomes container_entity_id on instance
    entities_with_room = [
        (e.id, e.room, e.container_id) for e in sorted_entities if e.room
    ]

    async with pool.acquire() as conn, conn.transaction():
        # Delete entities not in current files (CASCADE deletes instances)
        deleted = await conn.execute(
            "DELETE FROM entities WHERE id != ALL($1::text[])",
            all_entity_ids,
        )
        if deleted != "DELETE 0":
            logger.info(f"Removed stale entities: {deleted}")

        # Upsert all entities in topological order
        for entity in sorted_entities:
            await conn.execute(
                """INSERT INTO entities (
                    id, name, prototype_id,
                    description_short, description_long,
                    on_look, on_touch, on_attack, on_use, on_take,
                    on_open, on_close, on_drop,
                    contents_visible, spawn_mode, focus_mode, rarity
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                          $13, $14, $15::spawn_mode, $16::focus_mode, $17::rarity)
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
                    contents_visible = $14,
                    spawn_mode = $15::spawn_mode,
                    focus_mode = $16::focus_mode,
                    rarity = $17::rarity
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
                entity.contents_visible,
                entity.spawn_mode,
                entity.focus_mode,
                entity.rarity,
            )

        # Delete orphan room instances not in current rec files
        # (Inventory instances with owner_id are preserved)
        if entities_with_room:
            # Delete room instances for entity/room pairs not in rec files
            await conn.execute(
                """DELETE FROM entity_instances
                WHERE room IS NOT NULL
                  AND (entity_id, room) NOT IN (
                      SELECT * FROM unnest($1::text[], $2::text[])
                  )""",
                [e[0] for e in entities_with_room],
                [e[1] for e in entities_with_room],
            )
        else:
            # No entities with rooms - delete all room instances
            await conn.execute("DELETE FROM entity_instances WHERE room IS NOT NULL")

        # Create entity_instances for entities with Room field
        # container_entity_id comes from Container field in rec file
        if entities_with_room:
            await conn.executemany(
                """INSERT INTO entity_instances (entity_id, room, container_entity_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (entity_id, room) WHERE room IS NOT NULL
                DO UPDATE SET container_entity_id = $3""",
                entities_with_room,
            )
            logger.info(f"Ensured {len(entities_with_room)} entity instances exist")

        # Sync entity tags
        await _sync_entity_tags(conn, sorted_entities)

        # Load and sync spawning pools
        spawning_pools = load_spawning_pools_from_rec(world_file)
        await _sync_spawning_pools(conn, spawning_pools, room_ids, all_entity_ids)

    logger.info(f"Synced {len(sorted_entities)} entities to database")

    return len(sorted_entities)


async def _sync_entity_tags(conn: asyncpg.Connection, entities: list[Entity]) -> None:
    """Sync entity tags to database.

    Deletes all existing tags and inserts current tags from entities.
    This ensures tags stay in sync with the rec file.

    Args:
        conn: Database connection (in transaction)
        entities: List of entities with tags
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


async def _sync_spawning_pools(
    conn: asyncpg.Connection,
    pools: list[SpawningPool],
    room_ids: set[str],
    entity_ids: list[str],
) -> None:
    """Sync spawning pools to database.

    Validates references and upserts pools. Preserves last_spawn_at timestamps.

    Args:
        conn: Database connection (in transaction)
        pools: List of SpawningPool objects
        room_ids: Valid room IDs for validation
        entity_ids: Valid entity IDs for container validation
    """
    if not pools:
        # No pools - delete any existing
        await conn.execute("DELETE FROM spawning_pools")
        return

    entity_id_set = set(entity_ids)

    # Validate pool references
    for pool in pools:
        if pool.room not in room_ids:
            raise ValueError(
                f"SpawningPool '{pool.id}' references invalid room '{pool.room}'"
            )
        if pool.container_id and pool.container_id not in entity_id_set:
            raise ValueError(
                f"SpawningPool '{pool.id}' references invalid container "
                f"'{pool.container_id}'"
            )

    pool_ids = [p.id for p in pools]

    # Delete pools not in current files
    await conn.execute(
        "DELETE FROM spawning_pools WHERE id != ALL($1::text[])",
        pool_ids,
    )

    # Upsert pools (preserve last_spawn_at)
    for pool in pools:
        await conn.execute(
            """INSERT INTO spawning_pools (
                id, room, container_id, tag_query, max_count, respawn_interval_minutes
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id) DO UPDATE SET
                room = $2,
                container_id = $3,
                tag_query = $4,
                max_count = $5,
                respawn_interval_minutes = $6
            """,
            pool.id,
            pool.room,
            pool.container_id,
            pool.tag_query,
            pool.max_count,
            pool.respawn_interval_minutes,
        )

    logger.info(f"Synced {len(pools)} spawning pools")
