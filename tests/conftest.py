"""Pytest fixtures for database testing."""

import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from mudd.services.migrations import run_migrations
from mudd.services.zone_loader import (
    get_default_room,
    load_rooms_from_rec,
    load_zones_from_rec,
    sync_zones_and_rooms_to_db,
)

DB_HOST = os.environ.get("DB_HOST", "db")
TEST_DB_URL = f"postgresql://mudd:mudd@{DB_HOST}/mudd_test"
ADMIN_DB_URL = f"postgresql://mudd:mudd@{DB_HOST}/postgres"

# Default world file for testing
DEFAULT_WORLD_FILE = Path(__file__).parent.parent / "data" / "worlds" / "mansion.rec"


@pytest.fixture(scope="module")
def world_file() -> Path:
    """Return the path to the default test world file."""
    return DEFAULT_WORLD_FILE


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def test_db(world_file):
    """Create a fresh test database, run migrations, and tear down after tests.

    Also syncs zones/rooms from world_file so entity_instances FK constraints
    are satisfied when tests create entities with Room field.
    """
    # Create fresh test database
    admin = await asyncpg.connect(ADMIN_DB_URL)
    await admin.execute("DROP DATABASE IF EXISTS mudd_test")
    await admin.execute("CREATE DATABASE mudd_test")
    await admin.close()

    # Run migrations against test database
    pool = await asyncpg.create_pool(TEST_DB_URL)
    await run_migrations(pool)

    # Sync zones/rooms so entity_instances FK constraints work
    zones = load_zones_from_rec(world_file)
    rooms = load_rooms_from_rec(world_file)
    default_room = get_default_room(rooms)
    await sync_zones_and_rooms_to_db(pool, zones, rooms, default_room)

    yield pool

    # Teardown: close pool and drop test database
    await pool.close()
    admin = await asyncpg.connect(ADMIN_DB_URL)
    await admin.execute("DROP DATABASE mudd_test")
    await admin.close()
