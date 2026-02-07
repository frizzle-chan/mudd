"""Entity loader for syncing entity definitions and instances to PostgreSQL."""

import logging
from pathlib import Path

import asyncpg

from mudd.loaders.zone_loader import (
    load_entities_from_rec,
    load_rooms_from_rec,
    load_spawning_pools_from_rec,
)
from mudd.models import EntityDefinition, EntityInstance, SpawningPool

logger = logging.getLogger(__name__)


async def sync_entities(pool: asyncpg.Pool, world_file: Path) -> int:
    """Sync entities from a world rec file to database with validation.

    Full sync: deletes entities not in current files, upserts all current
    entities, and creates entity_instances for entities with Room field.
    Validates references and circular dependencies before database operations.
    Topologically sorts by prototype_id to satisfy FK constraints.

    Args:
        pool: Database connection pool
        world_file: Path to the world .rec file

    Returns:
        Number of entities synced.

    Raises:
        ValueError: If validation fails (circular deps, invalid references)
    """
    # Load data from rec file
    entities = load_entities_from_rec(world_file)
    rooms = load_rooms_from_rec(world_file)
    spawning_pools = load_spawning_pools_from_rec(world_file)

    room_ids = {r.id for r in rooms}

    # Sync entity definitions via model
    entity_stats = await EntityDefinition.sync_all(pool, entities, room_ids)

    # Prepare instance data: (entity_id, room, container_id)
    instance_data = [(e.id, e.room, e.container_id) for e in entities if e.room]

    # Sync world instances via model
    await EntityInstance.sync_world_instances(pool, instance_data)

    # Sync spawning pools via model
    entity_ids = {e.id for e in entities}
    await SpawningPool.sync_all(pool, spawning_pools, room_ids, entity_ids)

    return entity_stats.synced
