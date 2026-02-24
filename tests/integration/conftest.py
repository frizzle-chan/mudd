"""Integration test fixtures for per-test cleanup."""

from __future__ import annotations

from pathlib import Path

import pytest

from mudd.loaders.entity_loader import sync_entities

WORLD_FILE = Path("data/worlds/test_world.rec")


@pytest.fixture
async def clean_user_state(test_db, entity_cache, user_cache):
    """Reset user-mutable state after each test.

    Cleans up: users, focus, currency, player-owned entity instances.
    Then re-syncs world instances to restore destroyed/moved items.
    """
    yield

    # Rebuild user cache while users still exist (exercises bulk query path)
    await user_cache.rebuild(test_db)

    async with test_db.acquire() as conn:
        await conn.execute("DELETE FROM user_focus")
        await conn.execute("DELETE FROM user_trading_sessions")
        await conn.execute("DELETE FROM currency_ledger")
        await conn.execute("DELETE FROM currency_transactions")
        await conn.execute("DELETE FROM currency_accounts WHERE user_id != 0")
        await conn.execute("DELETE FROM user_skills")
        await conn.execute("DELETE FROM user_skills_channels")
        await conn.execute("DELETE FROM user_inventory_forums")
        await conn.execute("DELETE FROM shop_stock")
        await conn.execute("DELETE FROM entity_instances WHERE owner_id IS NOT NULL")
        await conn.execute(
            "DELETE FROM entity_instances WHERE room IS NULL AND owner_id IS NULL"
        )
        await conn.execute("DELETE FROM users")

    # Re-sync world instances to restore items destroyed during tests
    await sync_entities(test_db, WORLD_FILE)

    # Rebuild caches after cleanup
    await entity_cache.rebuild(test_db)
    user_cache._entries.clear()  # all users deleted above
