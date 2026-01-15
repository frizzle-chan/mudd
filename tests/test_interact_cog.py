"""Tests for Interact cog.

Tests:
1. Interact with valid verb and entity shows handler response
2. Unknown verb shows "You can't do that."
3. No entity match shows "You don't see '{target}' here."
4. Multiple entity matches shows disambiguation prompt
5. Handler is None shows "Nothing happens."
6. Sends ephemeral messages
7. Interact outside room shows error
8. Template render error shows fallback message
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from mudd.cogs.interact import Interact, _get_handler_text
from mudd.services.entity import EntityInstance, ResolvedEntity
from mudd.services.verb_action import VerbAction
from mudd.templating import TemplateRenderError


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
def mock_pool():
    """Create a mock database pool."""
    return MagicMock()


@pytest.fixture
def mock_interaction():
    """Create a mock Discord interaction."""
    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


@pytest.fixture
def interact_cog():
    """Create Interact cog with mock bot."""
    bot = MagicMock()
    return Interact(bot)


def make_entity(
    entity_id: str,
    name: str,
    on_attack: str | None = None,
    on_touch: str | None = None,
    on_look: str | None = None,
    on_use: str | None = None,
    on_take: str | None = None,
) -> ResolvedEntity:
    """Helper to create ResolvedEntity for tests."""
    return ResolvedEntity(
        id=entity_id,
        name=name,
        description_short=f"a {name}",
        description_long=None,
        on_look=on_look,
        on_touch=on_touch,
        on_attack=on_attack,
        on_use=on_use,
        on_take=on_take,
        contents_visible=None,
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
class TestInteractCog:
    """Test Interact cog command."""

    async def test_interact_shows_on_attack_response(
        self,
        interact_cog,
        mock_interaction,
        mock_visibility_service,
        mock_entity_service,
        mock_pool,
    ):
        """Interact with 'smash' shows on_attack handler."""
        mock_interaction.channel.name = "foyer"

        vase = make_entity(
            "vase",
            "Fancy Vase",
            on_attack="You smash the {{ name }} into pieces!",
        )
        vase_instance = make_instance(vase, "foyer")

        mock_entity_service.get_room_entities = AsyncMock(return_value=[vase_instance])

        with (
            patch(
                "mudd.cogs.interact.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.interact.get_entity_service",
                return_value=mock_entity_service,
            ),
            patch("mudd.cogs.interact.get_pool", return_value=mock_pool),
            patch(
                "mudd.cogs.interact.match_verb",
                return_value=VerbAction.ON_ATTACK,
            ),
        ):
            await interact_cog.interact.callback(
                interact_cog, mock_interaction, action="smash", target="vase"
            )

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]
        assert "You smash the *Fancy Vase* into pieces!" in message

    async def test_interact_unknown_verb(
        self,
        interact_cog,
        mock_interaction,
        mock_visibility_service,
        mock_entity_service,
        mock_pool,
    ):
        """Unknown verb shows 'You can't do that.'"""
        mock_interaction.channel.name = "foyer"

        vase = make_entity("vase", "Fancy Vase")
        vase_instance = make_instance(vase, "foyer")

        mock_entity_service.get_room_entities = AsyncMock(return_value=[vase_instance])

        with (
            patch(
                "mudd.cogs.interact.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.interact.get_entity_service",
                return_value=mock_entity_service,
            ),
            patch("mudd.cogs.interact.get_pool", return_value=mock_pool),
            patch("mudd.cogs.interact.match_verb", return_value=None),
        ):
            await interact_cog.interact.callback(
                interact_cog, mock_interaction, action="pet", target="vase"
            )

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]
        assert message == "You can't do that."

    async def test_interact_no_entity_match(
        self,
        interact_cog,
        mock_interaction,
        mock_visibility_service,
        mock_entity_service,
    ):
        """No entity match shows 'You don't see' message."""
        mock_interaction.channel.name = "foyer"

        table = make_entity("table", "Wooden Table")
        table_instance = make_instance(table, "foyer")

        mock_entity_service.get_room_entities = AsyncMock(return_value=[table_instance])

        with (
            patch(
                "mudd.cogs.interact.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.interact.get_entity_service",
                return_value=mock_entity_service,
            ),
        ):
            await interact_cog.interact.callback(
                interact_cog, mock_interaction, action="smash", target="xyz"
            )

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]
        assert "You don't see 'xyz' here." in message

    async def test_interact_disambiguation(
        self,
        interact_cog,
        mock_interaction,
        mock_visibility_service,
        mock_entity_service,
    ):
        """Multiple entity matches shows disambiguation prompt."""
        mock_interaction.channel.name = "foyer"

        vase1 = make_entity("vase1", "Flower Vase")
        vase2 = make_entity("vase2", "Fancy Vase")
        vase1_instance = make_instance(vase1, "foyer")
        vase2_instance = make_instance(vase2, "foyer")

        mock_entity_service.get_room_entities = AsyncMock(
            return_value=[vase1_instance, vase2_instance]
        )

        with (
            patch(
                "mudd.cogs.interact.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.interact.get_entity_service",
                return_value=mock_entity_service,
            ),
        ):
            await interact_cog.interact.callback(
                interact_cog, mock_interaction, action="smash", target="vase"
            )

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]
        assert "Which one?" in message
        assert "*Flower Vase*" in message
        assert "*Fancy Vase*" in message

    async def test_interact_handler_none_shows_nothing_happens(
        self,
        interact_cog,
        mock_interaction,
        mock_visibility_service,
        mock_entity_service,
        mock_pool,
    ):
        """Handler is None shows 'Nothing happens.'"""
        mock_interaction.channel.name = "foyer"

        # Entity with no handlers
        vase = make_entity("vase", "Fancy Vase")
        vase_instance = make_instance(vase, "foyer")

        mock_entity_service.get_room_entities = AsyncMock(return_value=[vase_instance])

        with (
            patch(
                "mudd.cogs.interact.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.interact.get_entity_service",
                return_value=mock_entity_service,
            ),
            patch("mudd.cogs.interact.get_pool", return_value=mock_pool),
            patch(
                "mudd.cogs.interact.match_verb",
                return_value=VerbAction.ON_TOUCH,
            ),
        ):
            await interact_cog.interact.callback(
                interact_cog, mock_interaction, action="touch", target="vase"
            )

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]
        assert message == "Nothing happens."

    async def test_interact_sends_ephemeral_message(
        self,
        interact_cog,
        mock_interaction,
        mock_visibility_service,
        mock_entity_service,
        mock_pool,
    ):
        """Interact sends response as ephemeral message."""
        mock_interaction.channel.name = "foyer"

        vase = make_entity("vase", "Fancy Vase", on_attack="You smash it!")
        vase_instance = make_instance(vase, "foyer")

        mock_entity_service.get_room_entities = AsyncMock(return_value=[vase_instance])

        with (
            patch(
                "mudd.cogs.interact.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.interact.get_entity_service",
                return_value=mock_entity_service,
            ),
            patch("mudd.cogs.interact.get_pool", return_value=mock_pool),
            patch(
                "mudd.cogs.interact.match_verb",
                return_value=VerbAction.ON_ATTACK,
            ),
        ):
            await interact_cog.interact.callback(
                interact_cog, mock_interaction, action="smash", target="vase"
            )

        call_kwargs = mock_interaction.response.send_message.call_args[1]
        assert call_kwargs.get("ephemeral") is True

    async def test_interact_no_room(
        self,
        interact_cog,
        mock_interaction,
        mock_visibility_service,
    ):
        """Interact outside room shows error."""
        mock_interaction.channel.name = None

        with patch(
            "mudd.cogs.interact.get_visibility_service",
            return_value=mock_visibility_service,
        ):
            await interact_cog.interact.callback(
                interact_cog, mock_interaction, action="smash", target="vase"
            )

        mock_interaction.response.send_message.assert_called_once()
        message = mock_interaction.response.send_message.call_args[0][0]
        assert "You can't interact with anything here." in message

    async def test_interact_template_render_error_shows_fallback(
        self,
        interact_cog,
        mock_interaction,
        mock_visibility_service,
        mock_entity_service,
        mock_pool,
    ):
        """Template render error shows fallback message."""
        mock_interaction.channel.name = "foyer"

        vase = make_entity("vase", "Fancy Vase", on_attack="{{ undefined }}")
        vase_instance = make_instance(vase, "foyer")

        mock_entity_service.get_room_entities = AsyncMock(return_value=[vase_instance])

        with (
            patch(
                "mudd.cogs.interact.get_visibility_service",
                return_value=mock_visibility_service,
            ),
            patch(
                "mudd.cogs.interact.get_entity_service",
                return_value=mock_entity_service,
            ),
            patch("mudd.cogs.interact.get_pool", return_value=mock_pool),
            patch("mudd.cogs.interact.match_verb", return_value=VerbAction.ON_ATTACK),
            patch("mudd.cogs.interact.render", side_effect=TemplateRenderError("test")),
        ):
            await interact_cog.interact.callback(
                interact_cog, mock_interaction, action="smash", target="vase"
            )

        message = mock_interaction.response.send_message.call_args[0][0]
        assert "*Fancy Vase* responds, but something went wrong." in message


class TestGetHandlerText:
    """Test _get_handler_text helper function."""

    def test_on_attack(self):
        entity = make_entity("vase", "Vase", on_attack="Smash!")
        assert _get_handler_text(entity, VerbAction.ON_ATTACK) == "Smash!"

    def test_on_touch(self):
        entity = make_entity("vase", "Vase", on_touch="Smooth.")
        assert _get_handler_text(entity, VerbAction.ON_TOUCH) == "Smooth."

    def test_on_look(self):
        entity = make_entity("vase", "Vase", on_look="It's pretty.")
        assert _get_handler_text(entity, VerbAction.ON_LOOK) == "It's pretty."

    def test_on_use(self):
        entity = make_entity("vase", "Vase", on_use="Used.")
        assert _get_handler_text(entity, VerbAction.ON_USE) == "Used."

    def test_on_take(self):
        entity = make_entity("vase", "Vase", on_take="Taken.")
        assert _get_handler_text(entity, VerbAction.ON_TAKE) == "Taken."

    def test_handler_none(self):
        entity = make_entity("vase", "Vase")
        assert _get_handler_text(entity, VerbAction.ON_ATTACK) is None
