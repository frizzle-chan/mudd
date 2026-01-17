"""Entity loader for syncing entity definitions and instances to PostgreSQL."""

import logging
from collections import defaultdict
from pathlib import Path

import asyncpg

from mudd.services.zone_loader import (
    Entity,
    load_entities_from_rec,
    load_rooms_from_rec,
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

    # Topological sort by prototype_id AND container_id (Kahn's algorithm)
    # Build dependency graph: entity -> entities that depend on it
    # An entity must be inserted BEFORE anything that references it as
    # prototype_id or container_id
    dependents: dict[str, list[str]] = defaultdict(list)
    in_degree = {e.id: 0 for e in entities}

    for entity in entities:
        if entity.prototype_id:
            dependents[entity.prototype_id].append(entity.id)
            in_degree[entity.id] += 1
        if entity.container_id:
            dependents[entity.container_id].append(entity.id)
            in_degree[entity.id] += 1

    # Start with entities that have no dependencies (no prototype or container)
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
        _invalidate_entity_cache()
        return 0

    # Load rooms for room reference validation
    rooms = load_rooms_from_rec(world_file)
    room_ids = {r.id for r in rooms}

    # Validate and sort entities
    sorted_entities = _validate_and_sort_entities(entities, room_ids)

    all_entity_ids = [e.id for e in sorted_entities]

    # Collect entities with Room field for instance creation
    entities_with_room = [(e.id, e.room) for e in sorted_entities if e.room]

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
                    id, name, prototype_id, container_id,
                    description_short, description_long,
                    on_look, on_touch, on_attack, on_use, on_take,
                    on_open, on_close,
                    contents_visible, spawn_mode, focus_mode
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                          $14, $15::spawn_mode, $16::focus_mode)
                ON CONFLICT (id) DO UPDATE SET
                    name = $2,
                    prototype_id = $3,
                    container_id = $4,
                    description_short = $5,
                    description_long = $6,
                    on_look = $7,
                    on_touch = $8,
                    on_attack = $9,
                    on_use = $10,
                    on_take = $11,
                    on_open = $12,
                    on_close = $13,
                    contents_visible = $14,
                    spawn_mode = $15::spawn_mode,
                    focus_mode = $16::focus_mode
                """,
                entity.id,
                entity.name,
                entity.prototype_id,
                entity.container_id,
                entity.description_short,
                entity.description_long,
                entity.on_look,
                entity.on_touch,
                entity.on_attack,
                entity.on_use,
                entity.on_take,
                entity.on_open,
                entity.on_close,
                entity.contents_visible,
                entity.spawn_mode,
                entity.focus_mode,
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
        if entities_with_room:
            await conn.executemany(
                """INSERT INTO entity_instances (entity_id, room)
                VALUES ($1, $2)
                ON CONFLICT (entity_id, room) WHERE room IS NOT NULL
                DO NOTHING""",
                entities_with_room,
            )
            logger.info(f"Ensured {len(entities_with_room)} entity instances exist")

    logger.info(f"Synced {len(sorted_entities)} entities to database")

    # Invalidate entity service cache after sync
    _invalidate_entity_cache()

    return len(sorted_entities)


def _invalidate_entity_cache() -> None:
    """Invalidate entity service cache if service is initialized."""
    from mudd.services.entity import get_entity_service, is_entity_service_initialized

    if is_entity_service_initialized():
        get_entity_service().invalidate_cache()
