"""PostgreSQL database connection management and migrations."""

import logging
import os
import re
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

# Migration configuration
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
MIGRATION_PATTERN = re.compile(r"^(\d+)_.*\.sql$")


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


async def init_database() -> asyncpg.Pool:
    """Initialize database: create pool and run migrations.

    Returns:
        The database connection pool.
    """
    pool = await get_pool()
    applied = await run_migrations(pool)
    if applied > 0:
        logger.info(f"Applied {applied} database migration(s)")
    return pool


async def _ensure_migrations_table(conn: asyncpg.Connection) -> None:
    """Create the migrations tracking table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            filename TEXT NOT NULL
        )
    """)


async def _get_applied_migrations(conn: asyncpg.Connection) -> set[int]:
    """Get the set of already-applied migration versions."""
    rows = await conn.fetch("SELECT version FROM schema_migrations")
    return {row["version"] for row in rows}


def _discover_migrations() -> list[tuple[int, Path]]:
    """Discover migration files and return sorted (version, path) pairs."""
    if not MIGRATIONS_DIR.exists():
        return []

    migrations = []
    for file in MIGRATIONS_DIR.iterdir():
        match = MIGRATION_PATTERN.match(file.name)
        if match:
            version = int(match.group(1))
            migrations.append((version, file))

    return sorted(migrations, key=lambda x: x[0])


async def run_migrations(pool: asyncpg.Pool) -> int:
    """
    Run pending migrations.

    Returns:
        Number of migrations applied.
    """
    async with pool.acquire() as conn:
        await _ensure_migrations_table(conn)
        applied = await _get_applied_migrations(conn)

        migrations = _discover_migrations()
        applied_count = 0

        for version, path in migrations:
            if version in applied:
                continue

            logger.info(f"Applying migration {path.name}")

            sql = path.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, filename) VALUES ($1, $2)",
                    version,
                    path.name,
                )

            applied_count += 1
            logger.info(f"Applied migration {path.name}")

        return applied_count
