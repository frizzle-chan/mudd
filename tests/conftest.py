"""Session-scoped test fixtures for integration tests."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from mudd.caches import EntityAutocompleteCache, UserCache
from mudd.database import run_migrations
from mudd.loaders.dialog_loader import load_all_dialogs
from mudd.loaders.entity_loader import sync_entities
from mudd.loaders.verb_loader import sync_verbs
from mudd.loaders.zone_loader import (
    get_default_room,
    load_rooms_from_rec,
    load_zones_from_rec,
)
from mudd.models import Room, Zone

WORLD_FILE = Path("data/worlds/test_world.rec")


@pytest.fixture(scope="session")
async def test_db():
    """Create ephemeral test database, run migrations, load test world."""
    db_host = os.environ.get("DB_HOST", "db")
    admin_dsn = f"postgresql://mudd:mudd@{db_host}:5432/mudd"
    db_name = f"mudd_test_{uuid4().hex[:8]}"

    # Create ephemeral database
    admin_conn = await asyncpg.connect(admin_dsn)
    await admin_conn.execute(f"CREATE DATABASE {db_name}")
    await admin_conn.close()

    # Create pool pointing to ephemeral DB
    test_dsn = f"postgresql://mudd:mudd@{db_host}:5432/{db_name}"
    pool = await asyncpg.create_pool(test_dsn, min_size=2, max_size=5)

    # Run migrations
    await run_migrations(pool)

    # Load test world (same order as sync cog)
    zones = load_zones_from_rec(WORLD_FILE)
    rooms = load_rooms_from_rec(WORLD_FILE)
    default_room = get_default_room(rooms)
    await Zone.sync_all(pool, zones, observers=())
    await Room.sync_all(pool, rooms, default_room, observers=())
    await sync_entities(pool, WORLD_FILE)
    await sync_verbs(pool)
    load_all_dialogs(Path("data/dialogs"))

    yield pool

    # Teardown
    await pool.close()
    admin_conn = await asyncpg.connect(admin_dsn)
    await admin_conn.execute(f"DROP DATABASE {db_name}")
    await admin_conn.close()


@pytest.fixture(scope="session")
async def entity_cache(test_db) -> EntityAutocompleteCache:
    cache = EntityAutocompleteCache()
    await cache.rebuild(test_db)
    return cache


@pytest.fixture(scope="session")
async def user_cache(test_db) -> UserCache:
    cache = UserCache()
    await cache.rebuild(test_db)
    return cache


@pytest.fixture(autouse=True, scope="session")
async def _wire_caches_to_helpers(entity_cache, user_cache):
    import tests.helpers as helpers

    helpers.entity_cache = entity_cache
    helpers.user_cache = user_cache
    yield
    helpers.entity_cache = None
    helpers.user_cache = None
