"""Tests for Look cog integration.

Tests:
1. Look cog formats room with entities correctly
2. Look cog handles room with no entities
3. Look cog handles room with no topic
4. Look cog shows nested container contents
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from mudd.cogs.look import Look
from mudd.services.entity import EntityInstance, ResolvedEntity


@pytest.fixture
def mock_visibility_service():
    """Create a mock visibility service."""
    service = MagicMock()
    service.wait_for_startup = AsyncMock()
    return service


@pytest.fixture
def mock_entity_service():
    """Create a mock entity service."""
    return MagicMock()


@pytest.fixture
def mock_interaction():
    """Create a mock Discord interaction."""
    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


@pytest.fixture
def look_cog():
    """Create Look cog with mock bot."""
    bot = MagicMock()
    return Look(bot)


def make_entity(
    entity_id: str,
    name: str,
    description_short: str,
    contents_visible: bool | None = None,
) -> ResolvedEntity:
    """Helper to create ResolvedEntity for tests."""
    return ResolvedEntity(
        id=entity_id,
        name=name,
        description_short=description_short,
        description_long=None,
        on_look=None,
        on_touch=None,
        on_attack=None,
        on_use=None,
        on_take=None,
        contents_visible=contents_visible,
        spawn_mode="none",
    )


def make_instance(entity: ResolvedEntity, room: str) -> EntityInstance:
    """Helper to create EntityInstance for tests."""
    return EntityInstance(
        instance_id=uuid4(),
        entity=entity,
        room=room,
        owner_id=None,
    )


@pytest.mark.asyncio
class TestLookCog:
    """Test Look cog command."""

    async def test_look_shows_room_description_and_entities(
        self, look_cog, mock_interaction, mock_visibility_service, mock_entity_service
    ):
        """Look shows room description followed by entities."""
        # Setup channel
        mock_interaction.channel.topic = "A grand foyer."
        mock_interaction.channel.name = "foyer"

        # Setup entities
        table = make_entity("table", "Wooden Table", "a {name} sits here", True)
        table_instance = make_instance(table, "foyer")

        mock_entity_service.get_top_level_room_entities = AsyncMock(
            return_value=[table_instance]
        )
        mock_entity_service.get_container_contents = AsyncMock(return_value=[])

        with (
            patch(
                "mudd.cogs.look.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.look.get_entity_service",
                return_value=mock_entity_service,
            ),
        ):
            # Call the callback directly (not the Command object)
            await look_cog.look.callback(look_cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]

        # Room description comes first
        assert message.startswith("A grand foyer.")
        # Followed by blank line and entity
        assert "\n\na *Wooden Table* sits here" in message

    async def test_look_shows_only_room_description_when_no_entities(
        self, look_cog, mock_interaction, mock_visibility_service, mock_entity_service
    ):
        """Look shows only room description when room has no entities."""
        mock_interaction.channel.topic = "An empty room."
        mock_interaction.channel.name = "empty-room"

        mock_entity_service.get_top_level_room_entities = AsyncMock(return_value=[])

        with (
            patch(
                "mudd.cogs.look.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.look.get_entity_service",
                return_value=mock_entity_service,
            ),
        ):
            await look_cog.look.callback(look_cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]
        assert message == "An empty room."

    async def test_look_handles_no_topic(
        self, look_cog, mock_interaction, mock_visibility_service, mock_entity_service
    ):
        """Look shows default message when channel has no topic."""
        mock_interaction.channel.topic = None
        mock_interaction.channel.name = "foyer"

        mock_entity_service.get_top_level_room_entities = AsyncMock(return_value=[])

        with (
            patch(
                "mudd.cogs.look.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.look.get_entity_service",
                return_value=mock_entity_service,
            ),
        ):
            await look_cog.look.callback(look_cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]
        assert message == "You see nothing special."

    async def test_look_shows_container_contents(
        self, look_cog, mock_interaction, mock_visibility_service, mock_entity_service
    ):
        """Look shows nested contents for containers with contents_visible=True."""
        mock_interaction.channel.topic = "A foyer."
        mock_interaction.channel.name = "foyer"

        # Table with visible contents
        table = make_entity(
            "table", "Wooden Table", "a {name} sits here", contents_visible=True
        )
        table_instance = make_instance(table, "foyer")

        # Vase inside table
        vase = make_entity("vase", "Flower Vase", "a {name}", contents_visible=None)
        vase_instance = make_instance(vase, "foyer")

        mock_entity_service.get_top_level_room_entities = AsyncMock(
            return_value=[table_instance]
        )
        mock_entity_service.get_container_contents = AsyncMock(
            return_value=[vase_instance]
        )

        with (
            patch(
                "mudd.cogs.look.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.look.get_entity_service",
                return_value=mock_entity_service,
            ),
        ):
            await look_cog.look.callback(look_cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]

        # Should show nested contents
        assert "a *Wooden Table* sits here. On it: a *Flower Vase*" in message

    async def test_look_sends_ephemeral_message(
        self, look_cog, mock_interaction, mock_visibility_service, mock_entity_service
    ):
        """Look sends response as ephemeral message."""
        mock_interaction.channel.topic = "A room."
        mock_interaction.channel.name = "room"

        mock_entity_service.get_top_level_room_entities = AsyncMock(return_value=[])

        with (
            patch(
                "mudd.cogs.look.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.look.get_entity_service",
                return_value=mock_entity_service,
            ),
        ):
            await look_cog.look.callback(look_cog, mock_interaction)

        # Check ephemeral=True
        call_kwargs = mock_interaction.response.send_message.call_args[1]
        assert call_kwargs.get("ephemeral") is True
