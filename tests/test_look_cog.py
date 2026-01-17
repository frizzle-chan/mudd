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


@pytest.fixture(autouse=True)
def mock_focus_context_service():
    """Auto-mock the focus context service for all tests."""
    mock_service = MagicMock()
    mock_service.is_entity_in_focus = AsyncMock(return_value=False)
    mock_service.clear_focus = AsyncMock(return_value=None)
    mock_service.update_focus_timestamp = AsyncMock()
    with patch(
        "mudd.cogs.look.get_focus_context_service",
        return_value=mock_service,
    ):
        yield mock_service


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
        on_open=None,
        on_close=None,
        contents_visible=contents_visible,
        spawn_mode="none",
        focus_mode="none",
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
        table = make_entity("table", "Wooden Table", "a {{ name }} sits here", True)
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

        # Table with visible contents - template controls how contents are shown
        table = make_entity(
            "table",
            "Wooden Table",
            "a {{ name }} sits here{% if contents %}. On it:{{ contents }}{% endif %}",
            contents_visible=True,
        )
        table_instance = make_instance(table, "foyer")

        # Vase inside table
        vase = make_entity("vase", "Flower Vase", "a {{ name }}", contents_visible=None)
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

        # Should show nested contents via template
        assert "a *Wooden Table* sits here. On it:" in message
        assert "a *Flower Vase*" in message

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

    async def test_look_at_entity_shows_long_description(
        self, look_cog, mock_interaction, mock_visibility_service, mock_entity_service
    ):
        """Look at specific entity shows description_long."""
        mock_interaction.channel.topic = "A grand foyer."
        mock_interaction.channel.name = "foyer"

        # Entity with description_long
        table = ResolvedEntity(
            id="table",
            name="Wooden Table",
            description_short="a {{ name }} sits here",
            description_long="A sturdy oak table with worn edges.",
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            contents_visible=None,
            spawn_mode="none",
            focus_mode="none",
        )
        table_instance = make_instance(table, "foyer")

        mock_entity_service.get_room_entities = AsyncMock(return_value=[table_instance])
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
            # Look at entity by name prefix
            await look_cog.look.callback(look_cog, mock_interaction, at="wood")

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]

        # Should show long description
        assert "A sturdy oak table with worn edges." in message

    async def test_look_at_entity_disambiguation(
        self, look_cog, mock_interaction, mock_visibility_service, mock_entity_service
    ):
        """Multiple matching entities shows disambiguation prompt."""
        mock_interaction.channel.topic = "A grand foyer."
        mock_interaction.channel.name = "foyer"

        # Two entities starting with "flower"
        vase = make_entity("vase", "Flower Vase", "a {{ name }}")
        pot = make_entity("pot", "Flower Pot", "a {{ name }}")
        vase_instance = make_instance(vase, "foyer")
        pot_instance = make_instance(pot, "foyer")

        mock_entity_service.get_room_entities = AsyncMock(
            return_value=[vase_instance, pot_instance]
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
            await look_cog.look.callback(look_cog, mock_interaction, at="flower")

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]

        # Should show disambiguation
        assert "Which one?" in message
        assert "*Flower Vase*" in message
        assert "*Flower Pot*" in message

    async def test_look_at_entity_no_match(
        self, look_cog, mock_interaction, mock_visibility_service, mock_entity_service
    ):
        """No matching entity shows 'not found' message and room description."""
        mock_interaction.channel.topic = "A grand foyer."
        mock_interaction.channel.name = "foyer"

        table = make_entity("table", "Wooden Table", "a {{ name }}")
        table_instance = make_instance(table, "foyer")

        mock_entity_service.get_room_entities = AsyncMock(return_value=[table_instance])

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
            await look_cog.look.callback(look_cog, mock_interaction, at="xyz")

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]

        # Should show not found and room description
        assert "You don't see 'xyz' here." in message
        assert "A grand foyer." in message
