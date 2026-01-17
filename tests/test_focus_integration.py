"""Integration tests for focus behavior through cog callbacks.

Tests the full focus lifecycle with a real database:
1. ON_OPEN establishes focus in database
2. ON_CLOSE clears focus from database and returns on_close template
3. /look Room escape clears focus from database
4. Movement clears focus from database (tested via FocusContextService)

Uses the test database with synced entities from mansion.rec which includes
library_records (Wooden Chest) with focus_mode='container' inherited from
the chest prototype.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

import mudd.services.entity as entity_module
from mudd.cogs.interact import Interact
from mudd.cogs.look import Look
from mudd.services.entity import init_entity_service
from mudd.services.entity_loader import sync_entities
from mudd.services.focus_context import FocusContextService
from mudd.services.verb_action import VerbAction

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def focus_db(test_db, world_file):
    """Sync entities to test database for focus integration tests."""
    await sync_entities(test_db, world_file)
    yield test_db


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def test_user(focus_db):
    """Create a test user for all tests in this module."""
    user_id = 987654321
    await focus_db.execute(
        "INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING", user_id
    )
    yield user_id


async def get_focus_from_db(pool, user_id: int):
    """Helper to get raw focus record from database."""
    return await pool.fetchrow("SELECT * FROM user_focus WHERE user_id = $1", user_id)


async def clear_focus_directly(pool, user_id: int):
    """Helper to clear focus directly in database."""
    await pool.execute("DELETE FROM user_focus WHERE user_id = $1", user_id)


def make_mock_interaction(user_id: int, room: str, topic: str = "A room."):
    """Create a mock Discord interaction for testing."""
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.channel = MagicMock()
    interaction.channel.name = room
    interaction.channel.topic = topic
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


class TestOnOpenEstablishesFocus:
    """Test that ON_OPEN action establishes focus in database."""

    async def test_open_container_establishes_focus(self, focus_db, test_user):
        """Opening a container with focus_mode='container' sets focus in DB."""
        await clear_focus_directly(focus_db, test_user)

        # Patch get_pool to return test database
        async def mock_get_pool():
            return focus_db

        # Create cog and interaction
        bot = MagicMock()
        cog = Interact(bot)
        interaction = make_mock_interaction(
            test_user, "library", "The mansion library."
        )

        # Create patched services
        visibility_service = MagicMock()
        visibility_service.wait_for_startup = AsyncMock()

        # Patch all services to use test database
        interact_vis = "mudd.cogs.interact.get_visibility_service"
        with (
            patch(interact_vis, return_value=visibility_service),
            patch("mudd.cogs.interact.get_pool", mock_get_pool),
            patch("mudd.cogs.interact.match_verb", return_value=VerbAction.ON_OPEN),
            patch("mudd.services.entity.get_pool", mock_get_pool),
            patch("mudd.services.focus_context.get_pool", mock_get_pool),
        ):
            # Initialize services with test database
            original_service = entity_module._service
            entity_module._service = None

            try:
                entity_service = init_entity_service()

                with patch(
                    "mudd.cogs.interact.get_entity_service",
                    return_value=entity_service,
                ):
                    # Create fresh focus service for this test
                    focus_service = FocusContextService()

                    with patch(
                        "mudd.cogs.interact.get_focus_context_service",
                        return_value=focus_service,
                    ):
                        # Open the wooden chest (library_records)
                        await cog.interact.callback(
                            cog, interaction, action="open", target="Wooden Chest"
                        )

                # Verify focus was established in database
                focus_row = await get_focus_from_db(focus_db, test_user)
                assert focus_row is not None, "Focus should be set in database"
                assert focus_row["entity_id"] == "library_records"
                assert focus_row["room"] == "library"

                # Verify response was sent
                interaction.response.send_message.assert_called_once()
                message = interaction.response.send_message.call_args[0][0]
                assert "open" in message.lower()
            finally:
                entity_module._service = original_service


class TestOnCloseClearsFocus:
    """Test that ON_CLOSE action clears focus and returns on_close template."""

    async def test_close_container_clears_focus(self, focus_db, test_user):
        """Closing clears focus from DB and includes on_close message."""
        # First set up focus directly
        await focus_db.execute(
            """
            INSERT INTO user_focus (user_id, room, entity_id, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (user_id) DO UPDATE SET
                room = EXCLUDED.room,
                entity_id = EXCLUDED.entity_id,
                updated_at = EXCLUDED.updated_at
            """,
            test_user,
            "library",
            "library_records",
        )

        # Verify focus exists
        focus_row = await get_focus_from_db(focus_db, test_user)
        assert focus_row is not None

        async def mock_get_pool():
            return focus_db

        bot = MagicMock()
        cog = Interact(bot)
        interaction = make_mock_interaction(
            test_user, "library", "The mansion library."
        )

        visibility_service = MagicMock()
        visibility_service.wait_for_startup = AsyncMock()

        interact_vis = "mudd.cogs.interact.get_visibility_service"
        verb_patch = "mudd.cogs.interact.match_verb"
        with (
            patch(interact_vis, return_value=visibility_service),
            patch("mudd.cogs.interact.get_pool", mock_get_pool),
            patch(verb_patch, return_value=VerbAction.ON_CLOSE),
            patch("mudd.services.entity.get_pool", mock_get_pool),
            patch("mudd.services.focus_context.get_pool", mock_get_pool),
        ):
            original_service = entity_module._service
            entity_module._service = None

            try:
                entity_service = init_entity_service()

                with patch(
                    "mudd.cogs.interact.get_entity_service",
                    return_value=entity_service,
                ):
                    focus_service = FocusContextService()

                    with patch(
                        "mudd.cogs.interact.get_focus_context_service",
                        return_value=focus_service,
                    ):
                        # Close the wooden chest
                        await cog.interact.callback(
                            cog, interaction, action="close", target="Wooden Chest"
                        )

                # Verify focus was cleared from database
                focus_row = await get_focus_from_db(focus_db, test_user)
                assert focus_row is None, "Focus should be cleared from database"

                # Verify response includes close message
                interaction.response.send_message.assert_called_once()
                message = interaction.response.send_message.call_args[0][0]
                assert "close" in message.lower()
            finally:
                entity_module._service = original_service


class TestLookRoomClearsFocus:
    """Test that /look Room clears focus from database."""

    async def test_look_room_clears_focus(self, focus_db, test_user):
        """Selecting 'Room' from /look autocomplete clears focus."""
        # Set up focus directly
        await focus_db.execute(
            """
            INSERT INTO user_focus (user_id, room, entity_id, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (user_id) DO UPDATE SET
                room = EXCLUDED.room,
                entity_id = EXCLUDED.entity_id,
                updated_at = EXCLUDED.updated_at
            """,
            test_user,
            "library",
            "library_records",
        )

        # Verify focus exists
        focus_row = await get_focus_from_db(focus_db, test_user)
        assert focus_row is not None

        async def mock_get_pool():
            return focus_db

        bot = MagicMock()
        cog = Look(bot)
        interaction = make_mock_interaction(
            test_user, "library", "The mansion library."
        )

        visibility_service = MagicMock()
        visibility_service.wait_for_startup = AsyncMock()
        visibility_service.get_room_name = AsyncMock(return_value="Library")

        look_vis = "mudd.cogs.look.get_visibility_service"
        with (
            patch(look_vis, return_value=visibility_service),
            patch("mudd.services.entity.get_pool", mock_get_pool),
            patch("mudd.services.focus_context.get_pool", mock_get_pool),
        ):
            original_service = entity_module._service
            entity_module._service = None

            try:
                entity_service = init_entity_service()

                with patch(
                    "mudd.cogs.look.get_entity_service",
                    return_value=entity_service,
                ):
                    focus_service = FocusContextService()

                    with patch(
                        "mudd.cogs.look.get_focus_context_service",
                        return_value=focus_service,
                    ):
                        # Look at "Room" which should clear focus
                        await cog.look.callback(cog, interaction, at="Room")

                # Verify focus was cleared from database
                focus_row = await get_focus_from_db(focus_db, test_user)
                assert focus_row is None, "Focus should be cleared at Room"

                # Verify response includes close message from on_close template
                interaction.response.send_message.assert_called_once()
                message = interaction.response.send_message.call_args[0][0]
                # Should contain either the on_close template or fallback
                assert "close" in message.lower() or "step away" in message.lower()
            finally:
                entity_module._service = original_service


class TestMovementClearsFocus:
    """Test that movement clears focus via FocusContextService."""

    async def test_clear_focus_for_movement(self, focus_db, test_user):
        """Clearing focus with reason='movement' removes from DB."""
        # Set up focus directly
        await focus_db.execute(
            """
            INSERT INTO user_focus (user_id, room, entity_id, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (user_id) DO UPDATE SET
                room = EXCLUDED.room,
                entity_id = EXCLUDED.entity_id,
                updated_at = EXCLUDED.updated_at
            """,
            test_user,
            "library",
            "library_records",
        )

        async def mock_get_pool():
            return focus_db

        with patch("mudd.services.focus_context.get_pool", mock_get_pool):
            service = FocusContextService()

            # Clear focus with movement reason (as would happen during room change)
            result = await service.clear_focus(test_user, reason="movement")

            # Movement shouldn't return on_close message
            assert result is None

            # Verify focus was cleared
            focus_row = await get_focus_from_db(focus_db, test_user)
            assert focus_row is None, "Focus should be cleared on movement"
