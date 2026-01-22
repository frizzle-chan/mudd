"""Pytest fixtures for database testing.

Session-scoped test database with world data sync. Individual tests use
the `clean_user_state` fixture for isolation via table cleanup.
"""

import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from mudd.database import run_migrations
from mudd.loaders.entity_loader import sync_entities
from mudd.loaders.verb_loader import sync_verbs
from mudd.loaders.zone_loader import (
    get_default_room,
    load_rooms_from_rec,
    load_zones_from_rec,
    sync_zones_and_rooms_to_db,
)

DB_HOST = os.environ.get("DB_HOST", "db")
TEST_DB_URL = f"postgresql://mudd:mudd@{DB_HOST}/mudd_test"
ADMIN_DB_URL = f"postgresql://mudd:mudd@{DB_HOST}/postgres"

# Default world file and verbs dir for testing
DEFAULT_WORLD_FILE = Path(__file__).parent.parent / "data" / "worlds" / "mansion.rec"
DEFAULT_VERBS_DIR = Path(__file__).parent.parent / "data" / "verbs"


@pytest.fixture(scope="session")
def world_file() -> Path:
    """Return the path to the default test world file."""
    return DEFAULT_WORLD_FILE


@pytest.fixture(scope="session")
def verbs_dir() -> Path:
    """Return the path to the verbs directory."""
    return DEFAULT_VERBS_DIR


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_db(world_file):
    """Create a fresh test database, run migrations, sync world data.

    Session-scoped: one test database per test run, cleaned up after.
    Syncs zones, rooms, entities, and verbs so tests have full world data.
    """
    # Create fresh test database
    admin = await asyncpg.connect(ADMIN_DB_URL)
    await admin.execute("DROP DATABASE IF EXISTS mudd_test")
    await admin.execute("CREATE DATABASE mudd_test")
    await admin.close()

    # Run migrations against test database
    pool = await asyncpg.create_pool(TEST_DB_URL)
    await run_migrations(pool)

    # Sync zones/rooms
    zones = load_zones_from_rec(world_file)
    rooms = load_rooms_from_rec(world_file)
    default_room = get_default_room(rooms)
    await sync_zones_and_rooms_to_db(pool, zones, rooms, default_room)

    # Sync entities
    await sync_entities(pool, world_file)

    # Sync verbs
    await sync_verbs(pool)

    yield pool

    # Teardown: close pool and drop test database
    await pool.close()
    admin = await asyncpg.connect(ADMIN_DB_URL)
    await admin.execute("DROP DATABASE mudd_test")
    await admin.close()


@pytest_asyncio.fixture
async def clean_user_state(test_db):
    """Clean user-mutable tables before each test for isolation.

    Clears:
    - user_focus: focus state
    - entity_instances: player-owned and player-dropped items
    - users: user records (cascades to user_focus)
    """
    await test_db.execute("DELETE FROM user_focus")
    await test_db.execute("DELETE FROM entity_instances WHERE owner_id IS NOT NULL")
    await test_db.execute("DELETE FROM entity_instances WHERE player_dropped = TRUE")
    await test_db.execute("DELETE FROM users")
    yield test_db


@pytest_asyncio.fixture
async def test_client(clean_user_state):
    """Create a TestClient with clean user state for command-based tests.

    The TestClient provides a high-level interface for executing commands
    and tracking user state without patching.
    """
    from tests.harness import TestClient

    return TestClient(clean_user_state)
