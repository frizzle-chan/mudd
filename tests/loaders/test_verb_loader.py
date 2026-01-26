"""Tests for verb loader (sync_verbs function)."""

import pytest

from mudd.loaders.verb_loader import sync_verbs

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestSyncVerbs:
    """Test verb syncing from files to database."""

    async def test_sync_loads_verbs(self, test_db):
        """Verbs are loaded into database."""
        async with test_db.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM verbs")

        # Should have loaded some verbs
        assert count > 0

    async def test_sync_loads_all_actions(self, test_db):
        """All 8 actions have verbs loaded."""
        async with test_db.acquire() as conn:
            actions = await conn.fetch("SELECT DISTINCT action FROM verbs")

        action_names = {row["action"] for row in actions}
        expected = {
            "on_look",
            "on_touch",
            "on_attack",
            "on_use",
            "on_take",
            "on_open",
            "on_close",
            "on_drop",
        }
        assert action_names == expected

    async def test_sync_removes_deleted_verbs(self, test_db):
        """Verbs not in files are removed on sync."""
        async with test_db.acquire() as conn:
            # Insert a fake verb that doesn't exist in files
            await conn.execute(
                "INSERT INTO verbs (verb, action) VALUES ($1, $2::verb_action)",
                "xyzzy_fake_verb",
                "on_look",
            )

            # Verify it was inserted
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM verbs WHERE verb = $1",
                "xyzzy_fake_verb",
            )
            assert count == 1

        # Re-sync should remove it
        await sync_verbs(test_db)

        async with test_db.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM verbs WHERE verb = $1",
                "xyzzy_fake_verb",
            )
            assert count == 0
