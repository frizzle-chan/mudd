"""Pytest fixtures for database testing."""

import asyncpg
import pytest_asyncio

from mudd.services.migrations import run_migrations

TEST_DB_URL = "postgresql://mudd:mudd@db/mudd_test"
ADMIN_DB_URL = "postgresql://mudd:mudd@db/postgres"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def test_db():
    """Create a fresh test database, run migrations, and tear down after tests."""
    # Create fresh test database
    admin = await asyncpg.connect(ADMIN_DB_URL)
    await admin.execute("DROP DATABASE IF EXISTS mudd_test")
    await admin.execute("CREATE DATABASE mudd_test")
    await admin.close()

    # Run migrations against test database
    pool = await asyncpg.create_pool(TEST_DB_URL)
    await run_migrations(pool)
    yield pool

    # Teardown: close pool and drop test database
    await pool.close()
    admin = await asyncpg.connect(ADMIN_DB_URL)
    await admin.execute("DROP DATABASE mudd_test")
    await admin.close()
