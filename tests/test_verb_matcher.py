"""Tests for verb loader and matcher.

Tests:
1. sync_verbs loads verbs from files into database
2. match_verb returns correct action for exact match
3. match_verb returns correct action for fuzzy match (typo)
4. match_verb returns None when no match found
5. sync_verbs removes verbs no longer in files
"""

import pytest
import pytest_asyncio

from mudd.services.verb_loader import sync_verbs
from mudd.services.verb_matcher import match_verb

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def verbs_db(test_db):
    """Sync verbs to test database."""
    await sync_verbs(test_db)
    yield test_db


class TestSyncVerbs:
    """Test verb syncing from files to database."""

    async def test_sync_loads_verbs(self, verbs_db):
        """Verbs are loaded into database."""
        async with verbs_db.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM verbs")

        # Should have loaded some verbs
        assert count > 0

    async def test_sync_loads_all_actions(self, verbs_db):
        """All 5 actions have verbs loaded."""
        async with verbs_db.acquire() as conn:
            actions = await conn.fetch("SELECT DISTINCT action FROM verbs")

        action_names = {row["action"] for row in actions}
        expected = {"on_look", "on_touch", "on_attack", "on_use", "on_take"}
        assert action_names == expected

    async def test_sync_removes_deleted_verbs(self, verbs_db):
        """Verbs not in files are removed on sync."""
        async with verbs_db.acquire() as conn:
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
        await sync_verbs(verbs_db)

        async with verbs_db.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM verbs WHERE verb = $1",
                "xyzzy_fake_verb",
            )
            assert count == 0


class TestMatchVerb:
    """Test verb matching with exact and fuzzy matching."""

    async def test_exact_match_look(self, verbs_db):
        """Exact match for 'look' returns 'on_look'."""
        action = await match_verb(verbs_db, "look")
        assert action == "on_look"

    async def test_exact_match_smash(self, verbs_db):
        """Exact match for 'smash' returns 'on_attack'."""
        action = await match_verb(verbs_db, "smash")
        assert action == "on_attack"

    async def test_exact_match_touch(self, verbs_db):
        """Exact match for 'touch' returns 'on_touch'."""
        action = await match_verb(verbs_db, "touch")
        assert action == "on_touch"

    async def test_exact_match_use(self, verbs_db):
        """Exact match for 'use' returns 'on_use'."""
        action = await match_verb(verbs_db, "use")
        assert action == "on_use"

    async def test_exact_match_take(self, verbs_db):
        """Exact match for 'take' returns 'on_take'."""
        action = await match_verb(verbs_db, "take")
        assert action == "on_take"

    async def test_fuzzy_match_typo(self, verbs_db):
        """Fuzzy match for typo 'smassh' returns 'on_attack'."""
        # 'smassh' (double s) has ~0.625 similarity to 'smash', above 0.5 threshold
        action = await match_verb(verbs_db, "smassh")
        assert action == "on_attack"

    async def test_fuzzy_match_examine_typo(self, verbs_db):
        """Fuzzy match for typo 'examin' returns 'on_look'."""
        action = await match_verb(verbs_db, "examin")
        assert action == "on_look"

    async def test_no_match_gibberish(self, verbs_db):
        """No match for gibberish returns None."""
        action = await match_verb(verbs_db, "xyzzy")
        assert action is None

    async def test_no_match_empty_string(self, verbs_db):
        """No match for empty string returns None."""
        action = await match_verb(verbs_db, "")
        assert action is None

    async def test_case_insensitive(self, verbs_db):
        """Matching is case insensitive."""
        action = await match_verb(verbs_db, "LOOK")
        assert action == "on_look"

    async def test_whitespace_trimmed(self, verbs_db):
        """Whitespace is trimmed from input."""
        action = await match_verb(verbs_db, "  look  ")
        assert action == "on_look"
