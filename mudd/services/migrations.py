"""Database migration runner."""

import logging
import re
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
MIGRATION_PATTERN = re.compile(r"^(\d+)_.*\.sql$")


async def ensure_migrations_table(conn: asyncpg.Connection) -> None:
    """Create the migrations tracking table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            filename TEXT NOT NULL
        )
    """)


async def get_applied_migrations(conn: asyncpg.Connection) -> set[int]:
    """Get the set of already-applied migration versions."""
    rows = await conn.fetch("SELECT version FROM schema_migrations")
    return {row["version"] for row in rows}


def discover_migrations() -> list[tuple[int, Path]]:
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
        await ensure_migrations_table(conn)
        applied = await get_applied_migrations(conn)

        migrations = discover_migrations()
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
