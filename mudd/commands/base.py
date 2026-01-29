"""Base types and abstract class for action commands."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from discord import Interaction

from mudd.services.entity import ResolvedEntity
from mudd.services.trigger_effects import TriggerEffects
from mudd.types import UserContext

if TYPE_CHECKING:
    from mudd.services.rendering import RenderingService, RoomContext


@dataclass(frozen=True)
class ActionContext:
    """Immutable context passed to commands.

    Contains all information needed to execute an action command,
    including the Discord interaction, resolved entity, and template
    rendering context.
    """

    interaction: Interaction
    entity: ResolvedEntity
    instance_id: UUID
    room: str
    source: Literal["room", "inventory", "container"]
    user_context: UserContext
    container_contents: str
    focused_container: ResolvedEntity | None
    room_context: "RoomContext | None" = None


@dataclass(frozen=True)
class ActionResult:
    """Immutable result from command execution.

    Contains the rendered output text, collected effects from template
    rendering, and optional focus change signals.
    """

    output: str
    effects: TriggerEffects
    # Focus changes (for open/close)
    set_focus: ResolvedEntity | None = None
    clear_focus: bool = False


class ActionCommand(ABC):
    """Base class for verb action commands.

    Each command type implements get_handler_text() to specify which
    entity field to use as the template. Most commands use the default
    execute() which renders the template. Commands with special behavior
    (like open/close) override execute() to add focus signals.
    """

    def __init__(self, rendering: "RenderingService") -> None:
        self._rendering = rendering

    @abstractmethod
    def get_handler_text(self, entity: ResolvedEntity) -> str | None:
        """Get the entity's handler template for this action.

        Args:
            entity: The resolved entity being acted upon

        Returns:
            Handler template text, or None if no handler defined
        """
        pass

    async def execute(self, ctx: ActionContext) -> ActionResult:
        """Execute this command.

        Default implementation renders the handler template with full context.
        Override for custom behavior (e.g., focus changes).

        Args:
            ctx: Action context with entity, user, and container info

        Returns:
            ActionResult with rendered output and effects
        """
        handler_text = self.get_handler_text(ctx.entity)
        if handler_text is None:
            return ActionResult(output="Nothing happens.", effects=TriggerEffects())

        output, effects = await self._rendering.render_with_effects(
            handler_text,
            ctx.entity,
            ctx.user_context,
            ctx.container_contents,
            ctx.focused_container,
            ctx.room_context,
        )
        return ActionResult(output=output, effects=effects)
