"""Unit tests for action command classes."""

from typing import Literal
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from mudd.commands import COMMANDS, ActionContext, ActionResult, create_command
from mudd.commands.focus import CloseCommand, OpenCommand
from mudd.commands.inventory import DropCommand, TakeCommand
from mudd.commands.simple import AttackCommand, LookCommand, TouchCommand, UseCommand
from mudd.services.entity import ResolvedEntity
from mudd.services.rendering import RenderingService
from mudd.services.trigger_effects import TriggerEffects
from mudd.types import UserContext, VerbAction


@pytest.fixture
def rendering_service() -> RenderingService:
    """Create a RenderingService instance for tests."""
    return RenderingService()


@pytest.fixture
def mock_entity() -> ResolvedEntity:
    """Create a mock entity with all handler fields."""
    return ResolvedEntity(
        id="test_entity",
        name="Test Entity",
        description_short="A test entity.",
        description_long="A longer description of the test entity.",
        on_look="You look at the {{ name }}.",
        on_touch="You touch the {{ name }}.",
        on_attack="You attack the {{ name }}.",
        on_use="You use the {{ name }}.",
        on_take="{{ effects.pickup() }}You take the {{ name }}.",
        on_open="You open the {{ name }}.",
        on_close="You close the {{ name }}.",
        on_drop="{{ effects.drop() }}You drop the {{ name }}.",
        contents_visible=False,
        focus_mode="none",
        rarity="common",
    )


@pytest.fixture
def focusable_entity() -> ResolvedEntity:
    """Create an entity with focus_mode='container'."""
    return ResolvedEntity(
        id="container",
        name="Container",
        description_short="A container.",
        description_long=None,
        on_look="You look at the container.",
        on_touch=None,
        on_attack=None,
        on_use=None,
        on_take=None,
        on_open="You open the container.",
        on_close="You close the container.",
        on_drop=None,
        contents_visible=True,
        focus_mode="container",
        rarity="common",
    )


@pytest.fixture
def mock_interaction() -> MagicMock:
    """Create a mock Discord interaction."""
    interaction = MagicMock()
    interaction.user.id = 12345
    interaction.user.display_name = "TestUser"
    interaction.user.mention = "<@12345>"
    return interaction


@pytest.fixture
def action_context(
    mock_interaction: MagicMock, mock_entity: ResolvedEntity
) -> ActionContext:
    """Create an ActionContext for tests."""
    return ActionContext(
        interaction=mock_interaction,
        entity=mock_entity,
        instance_id=UUID("12345678-1234-1234-1234-123456789012"),
        room="test-room",
        source="room",
        user_context=UserContext(name="TestUser", mention="<@12345>"),
        container_contents="",
        balance_str="",
        focused_container=None,
    )


class TestCommandRegistry:
    """Tests for command registry and factory."""

    def test_all_verb_actions_registered(self):
        """All VerbAction values have a registered command."""
        for action in VerbAction:
            assert action in COMMANDS, f"Missing command for {action}"

    def test_create_command_returns_correct_types(
        self, rendering_service: RenderingService
    ):
        """create_command returns the correct command type for each action."""
        assert isinstance(
            create_command(VerbAction.ON_LOOK, rendering_service), LookCommand
        )
        assert isinstance(
            create_command(VerbAction.ON_TOUCH, rendering_service), TouchCommand
        )
        assert isinstance(
            create_command(VerbAction.ON_ATTACK, rendering_service), AttackCommand
        )
        assert isinstance(
            create_command(VerbAction.ON_USE, rendering_service), UseCommand
        )
        assert isinstance(
            create_command(VerbAction.ON_TAKE, rendering_service), TakeCommand
        )
        assert isinstance(
            create_command(VerbAction.ON_OPEN, rendering_service), OpenCommand
        )
        assert isinstance(
            create_command(VerbAction.ON_CLOSE, rendering_service), CloseCommand
        )
        assert isinstance(
            create_command(VerbAction.ON_DROP, rendering_service), DropCommand
        )

    def test_create_command_invalid_action(self, rendering_service: RenderingService):
        """create_command raises KeyError for invalid action."""
        with pytest.raises(KeyError):
            create_command("invalid_action", rendering_service)  # type: ignore


class TestSimpleCommands:
    """Tests for simple commands (look, touch, attack, use)."""

    def test_look_command_get_handler_text(self, mock_entity: ResolvedEntity):
        """LookCommand.get_handler_text returns on_look."""
        cmd = LookCommand(MagicMock())
        assert cmd.get_handler_text(mock_entity) == mock_entity.on_look

    def test_touch_command_get_handler_text(self, mock_entity: ResolvedEntity):
        """TouchCommand.get_handler_text returns on_touch."""
        cmd = TouchCommand(MagicMock())
        assert cmd.get_handler_text(mock_entity) == mock_entity.on_touch

    def test_attack_command_get_handler_text(self, mock_entity: ResolvedEntity):
        """AttackCommand.get_handler_text returns on_attack."""
        cmd = AttackCommand(MagicMock())
        assert cmd.get_handler_text(mock_entity) == mock_entity.on_attack

    def test_use_command_get_handler_text(self, mock_entity: ResolvedEntity):
        """UseCommand.get_handler_text returns on_use."""
        cmd = UseCommand(MagicMock())
        assert cmd.get_handler_text(mock_entity) == mock_entity.on_use

    def test_look_command_executes(
        self,
        rendering_service: RenderingService,
        action_context: ActionContext,
    ):
        """LookCommand.execute renders template and returns result."""
        cmd = LookCommand(rendering_service)
        result = cmd.execute(action_context)

        assert isinstance(result, ActionResult)
        assert "Test Entity" in result.output
        assert result.set_focus is None
        assert result.clear_focus is False

    def test_simple_command_no_handler_returns_nothing_happens(
        self, rendering_service: RenderingService
    ):
        """Command with no handler text returns 'Nothing happens.'"""
        entity = ResolvedEntity(
            id="empty",
            name="Empty",
            description_short=None,
            description_long=None,
            on_look=None,
            on_touch=None,
            on_attack=None,
            on_use=None,
            on_take=None,
            on_open=None,
            on_close=None,
            on_drop=None,
            contents_visible=False,
            focus_mode="none",
            rarity="common",
        )
        ctx = ActionContext(
            interaction=MagicMock(),
            entity=entity,
            instance_id=UUID("12345678-1234-1234-1234-123456789012"),
            room="test-room",
            source="room",
            user_context=UserContext(name="TestUser", mention="<@12345>"),
            container_contents="",
            balance_str="",
            focused_container=None,
        )
        cmd = LookCommand(rendering_service)
        result = cmd.execute(ctx)

        assert result.output == "Nothing happens."


class TestFocusCommands:
    """Tests for focus commands (open, close)."""

    def test_open_command_get_handler_text(self, mock_entity: ResolvedEntity):
        """OpenCommand.get_handler_text returns on_open."""
        cmd = OpenCommand(MagicMock())
        assert cmd.get_handler_text(mock_entity) == mock_entity.on_open

    def test_close_command_get_handler_text(self, mock_entity: ResolvedEntity):
        """CloseCommand.get_handler_text returns on_close."""
        cmd = CloseCommand(MagicMock())
        assert cmd.get_handler_text(mock_entity) == mock_entity.on_close

    def test_open_command_sets_focus_for_focusable_entity(
        self,
        rendering_service: RenderingService,
        focusable_entity: ResolvedEntity,
        mock_interaction: MagicMock,
    ):
        """OpenCommand sets set_focus for entities with focus_mode != 'none'."""
        instance_id = UUID("12345678-1234-1234-1234-123456789012")
        ctx = ActionContext(
            interaction=mock_interaction,
            entity=focusable_entity,
            instance_id=instance_id,
            room="test-room",
            source="room",
            user_context=UserContext(name="TestUser", mention="<@12345>"),
            container_contents="",
            balance_str="",
            focused_container=None,
        )
        cmd = OpenCommand(rendering_service)
        result = cmd.execute(ctx)

        # set_focus now returns instance_id (UUID) instead of entity
        assert result.set_focus == instance_id
        assert result.clear_focus is False

    def test_open_command_no_focus_for_non_focusable_entity(
        self,
        rendering_service: RenderingService,
        action_context: ActionContext,
    ):
        """OpenCommand does not set focus for entities with focus_mode='none'."""
        cmd = OpenCommand(rendering_service)
        result = cmd.execute(action_context)

        assert result.set_focus is None
        assert result.clear_focus is False

    def test_close_command_signals_clear_focus(
        self,
        rendering_service: RenderingService,
        action_context: ActionContext,
    ):
        """CloseCommand always signals clear_focus=True."""
        cmd = CloseCommand(rendering_service)
        result = cmd.execute(action_context)

        assert result.clear_focus is True
        assert result.set_focus is None


class TestInventoryCommands:
    """Tests for inventory commands (take, drop)."""

    def test_take_command_get_handler_text(self, mock_entity: ResolvedEntity):
        """TakeCommand.get_handler_text returns on_take."""
        cmd = TakeCommand(MagicMock())
        assert cmd.get_handler_text(mock_entity) == mock_entity.on_take

    def test_drop_command_get_handler_text(self, mock_entity: ResolvedEntity):
        """DropCommand.get_handler_text returns on_drop."""
        cmd = DropCommand(MagicMock())
        assert cmd.get_handler_text(mock_entity) == mock_entity.on_drop

    def test_take_command_sets_pickup_flag(
        self,
        rendering_service: RenderingService,
        action_context: ActionContext,
    ):
        """TakeCommand template with effects.pickup() sets the pickup flag."""
        cmd = TakeCommand(rendering_service)
        result = cmd.execute(action_context)

        assert result.effects.has_pickup is True
        assert "You take" in result.output

    def test_drop_command_sets_drop_flag(
        self,
        rendering_service: RenderingService,
        action_context: ActionContext,
    ):
        """DropCommand template with effects.drop() sets the drop flag."""
        cmd = DropCommand(rendering_service)
        result = cmd.execute(action_context)

        assert result.effects.has_drop is True
        assert "You drop" in result.output


class TestActionResult:
    """Tests for ActionResult dataclass."""

    def test_action_result_defaults(self):
        """ActionResult has sensible defaults."""
        effects = TriggerEffects()
        result = ActionResult(output="test", effects=effects)

        assert result.output == "test"
        assert result.effects is effects
        assert result.set_focus is None
        assert result.clear_focus is False

    def test_action_result_with_focus(self):
        """ActionResult can carry focus change signals."""
        effects = TriggerEffects()
        instance_id = UUID("12345678-1234-1234-1234-123456789012")
        result = ActionResult(
            output="test",
            effects=effects,
            set_focus=instance_id,
            clear_focus=True,
        )

        assert result.set_focus == instance_id
        assert result.clear_focus is True


class TestActionContext:
    """Tests for ActionContext dataclass."""

    def test_action_context_is_frozen(self, action_context: ActionContext):
        """ActionContext is immutable."""
        with pytest.raises(AttributeError):
            action_context.room = "another-room"  # type: ignore

    def test_action_context_source_types(
        self, mock_interaction: MagicMock, mock_entity: ResolvedEntity
    ):
        """ActionContext accepts valid source values."""
        sources: list[Literal["room", "inventory", "container"]] = [
            "room",
            "inventory",
            "container",
        ]
        for source in sources:
            ctx = ActionContext(
                interaction=mock_interaction,
                entity=mock_entity,
                instance_id=UUID("12345678-1234-1234-1234-123456789012"),
                room="test-room",
                source=source,
                user_context=UserContext(name="Test", mention="<@1>"),
                container_contents="",
                balance_str="",
                focused_container=None,
            )
            assert ctx.source == source
