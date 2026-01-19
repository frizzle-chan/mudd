"""Trigger and verb matching integration tests.

Tests the 7 on_* triggers (on_look, on_touch, on_attack, on_use, on_take,
on_open, on_close) and verb fuzzy matching including synonyms, typos,
and case insensitivity.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestTriggerTypes:
    """Tests each trigger type using dedicated test entities."""

    async def test_on_look_trigger(self, test_client):
        """Looking at Test Orb shows TEST_LOOK_RESPONSE."""
        user = await test_client.create_user(user_id=400000001, room="store-room")
        # First open the box to establish focus
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.look(user, at="Test Orb")
        assert "TEST_LOOK_RESPONSE" in response

    async def test_on_touch_trigger(self, test_client):
        """Touching Test Orb triggers TEST_TOUCH_RESPONSE."""
        user = await test_client.create_user(user_id=400000002, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="touch", target="Test Orb")
        assert "TEST_TOUCH_RESPONSE" in response

    async def test_on_attack_trigger(self, test_client):
        """Attacking Test Orb triggers TEST_ATTACK_RESPONSE."""
        user = await test_client.create_user(user_id=400000003, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="attack", target="Test Orb")
        assert "TEST_ATTACK_RESPONSE" in response

    async def test_on_use_trigger(self, test_client):
        """Using Test Gadget triggers TEST_USE_RESPONSE."""
        user = await test_client.create_user(user_id=400000004, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="use", target="Test Gadget")
        assert "TEST_USE_RESPONSE" in response

    async def test_on_take_trigger(self, test_client):
        """Taking Test Gadget triggers TEST_TAKE_RESPONSE."""
        user = await test_client.create_user(user_id=400000005, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="take", target="Test Gadget")
        assert "TEST_TAKE_RESPONSE" in response

    async def test_on_open_trigger(self, test_client):
        """Opening Test Lockbox triggers TEST_OPEN_RESPONSE."""
        user = await test_client.create_user(user_id=400000006, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(
            user, action="open", target="Test Lockbox"
        )
        assert "TEST_OPEN_RESPONSE" in response

    async def test_on_close_trigger(self, test_client):
        """Closing Test Lockbox triggers TEST_CLOSE_RESPONSE."""
        user = await test_client.create_user(user_id=400000007, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        await test_client.interact(user, action="open", target="Test Lockbox")
        response = await test_client.interact(
            user, action="close", target="Test Lockbox"
        )
        assert "TEST_CLOSE_RESPONSE" in response


class TestVerbFuzzyMatching:
    """Tests PostgreSQL pg_trgm fuzzy matching with 0.5 similarity threshold."""

    # Exact verbs
    async def test_exact_look_verb(self, test_client):
        """Exact 'look' verb triggers on_look."""
        user = await test_client.create_user(user_id=400000010, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.look(user, at="Test Orb")
        assert "TEST_LOOK_RESPONSE" in response

    async def test_exact_attack_verb(self, test_client):
        """Exact 'attack' verb triggers on_attack."""
        user = await test_client.create_user(user_id=400000011, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="attack", target="Test Orb")
        assert "TEST_ATTACK_RESPONSE" in response

    # Synonyms that map to canonical verbs
    async def test_synonym_examine_maps_to_look(self, test_client):
        """'examine' synonym maps to on_look."""
        user = await test_client.create_user(user_id=400000020, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="examine", target="Test Orb")
        assert "TEST_LOOK_RESPONSE" in response

    async def test_synonym_inspect_maps_to_look(self, test_client):
        """'inspect' synonym maps to on_look."""
        user = await test_client.create_user(user_id=400000021, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="inspect", target="Test Orb")
        assert "TEST_LOOK_RESPONSE" in response

    async def test_synonym_feel_maps_to_touch(self, test_client):
        """'feel' synonym maps to on_touch."""
        user = await test_client.create_user(user_id=400000022, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="feel", target="Test Orb")
        assert "TEST_TOUCH_RESPONSE" in response

    async def test_synonym_smash_maps_to_attack(self, test_client):
        """'smash' synonym maps to on_attack."""
        user = await test_client.create_user(user_id=400000023, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="smash", target="Test Orb")
        assert "TEST_ATTACK_RESPONSE" in response

    async def test_synonym_grab_maps_to_take(self, test_client):
        """'grab' synonym maps to on_take."""
        user = await test_client.create_user(user_id=400000024, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="grab", target="Test Gadget")
        assert "TEST_TAKE_RESPONSE" in response

    async def test_synonym_unlock_maps_to_open(self, test_client):
        """'unlock' synonym maps to on_open."""
        user = await test_client.create_user(user_id=400000025, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(
            user, action="unlock", target="Test Lockbox"
        )
        assert "TEST_OPEN_RESPONSE" in response

    async def test_synonym_shut_maps_to_close(self, test_client):
        """'shut' synonym maps to on_close."""
        user = await test_client.create_user(user_id=400000026, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        await test_client.interact(user, action="open", target="Test Lockbox")
        response = await test_client.interact(
            user, action="shut", target="Test Lockbox"
        )
        assert "TEST_CLOSE_RESPONSE" in response

    # Typo tolerance (pg_trgm fuzzy matching)
    # Note: Typos must have >0.5 similarity to match. Short typos like "opn"
    # don't have enough trigram overlap with "open" to meet the threshold.
    async def test_typo_oppen_matches_open(self, test_client):
        """Typo 'oppen' matches 'open' via fuzzy matching."""
        user = await test_client.create_user(user_id=400000030, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(
            user, action="oppen", target="Test Lockbox"
        )
        assert "TEST_OPEN_RESPONSE" in response

    async def test_typo_smaash_matches_smash(self, test_client):
        """Typo 'smaash' matches 'smash' via fuzzy matching."""
        user = await test_client.create_user(user_id=400000031, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="smaash", target="Test Orb")
        assert "TEST_ATTACK_RESPONSE" in response

    async def test_typo_graab_matches_grab(self, test_client):
        """Typo 'graab' matches 'grab' via fuzzy matching."""
        user = await test_client.create_user(user_id=400000032, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(
            user, action="graab", target="Test Gadget"
        )
        assert "TEST_TAKE_RESPONSE" in response

    # Unknown verbs should be rejected
    async def test_unknown_verb_dance_rejected(self, test_client):
        """Unknown verb 'dance' returns error message."""
        user = await test_client.create_user(user_id=400000040, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="dance", target="Test Orb")
        assert "can't do that" in response.lower()

    async def test_gibberish_verb_rejected(self, test_client):
        """Gibberish verb 'xyzqwk' returns error message."""
        user = await test_client.create_user(user_id=400000041, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="xyzqwk", target="Test Orb")
        assert "can't do that" in response.lower()


class TestVerbCaseInsensitivity:
    """Tests that verb matching is case-insensitive."""

    async def test_uppercase_verb_matches(self, test_client):
        """Uppercase 'TOUCH' matches on_touch."""
        user = await test_client.create_user(user_id=400000050, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="TOUCH", target="Test Orb")
        assert "TEST_TOUCH_RESPONSE" in response

    async def test_mixed_case_verb_matches(self, test_client):
        """Mixed case 'SmAsH' matches on_attack."""
        user = await test_client.create_user(user_id=400000051, room="store-room")
        await test_client.interact(user, action="open", target="Cardboard Box")
        response = await test_client.interact(user, action="SmAsH", target="Test Orb")
        assert "TEST_ATTACK_RESPONSE" in response
