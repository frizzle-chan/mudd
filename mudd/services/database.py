"""PostgreSQL database connection management."""

import logging
import os

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the database connection pool."""
    global _pool
    if _pool is None:
        database_url = os.environ.get(
            "DATABASE_URL",
            "postgresql://mudd:mudd@db:5432/mudd",
        )
        _pool = await asyncpg.create_pool(
            database_url,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
        logger.info("Database connection pool created")
    return _pool


async def close_pool() -> None:
    """Close the database connection pool gracefully."""
    global _pool
    if _pool:
        await _pool.close()
        logger.info("Database connection pool closed")
    _pool = None


async def init_database() -> None:
    """Initialize database: create pool and run migrations."""
    from mudd.services.migrations import run_migrations

    pool = await get_pool()
    applied = await run_migrations(pool)
    if applied > 0:
        logger.info(f"Applied {applied} database migration(s)")
