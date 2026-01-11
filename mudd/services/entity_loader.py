"""Entity loader for syncing entity definitions to PostgreSQL."""

import logging
from collections import defaultdict

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


async def sync_entities(pool: asyncpg.Pool) -> int:
    """Sync entities from rec files to database with validation.

    Full sync: deletes entities not in current files, upserts all current
    entities. Validates references and circular dependencies before database
    operations. Topologically sorts by prototype_id to satisfy FK constraints.

    Returns:
        Number of entities synced.

    Raises:
        ValueError: If validation fails (circular deps, invalid references)
    """
    entities = load_entities_from_rec()

    if not entities:
        logger.warning("No entities found in rec files - skipping sync")
        return 0

    # Load rooms for room reference validation
    rooms = load_rooms_from_rec()
    room_ids = {r.id for r in rooms}

    # Validate and sort entities
    sorted_entities = _validate_and_sort_entities(entities, room_ids)

    all_entity_ids = [e.id for e in sorted_entities]

    async with pool.acquire() as conn, conn.transaction():
        # Delete entities not in current files
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
                    contents_visible, spawn_mode
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                          $13::spawn_mode)
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
                    contents_visible = $12,
                    spawn_mode = $13::spawn_mode
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
                entity.contents_visible,
                entity.spawn_mode,
            )

    logger.info(f"Synced {len(sorted_entities)} entities to database")
    return len(sorted_entities)
