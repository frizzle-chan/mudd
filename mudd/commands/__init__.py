"""Command pattern for verb actions.

This module provides the Command pattern implementation for handling
different verb actions (look, touch, attack, use, take, open, close, drop).
Each command encapsulates the logic for rendering its handler template
and any special behavior (like focus changes for open/close).

Usage:
    from mudd.commands import create_command
    from mudd.types import VerbAction

    command = create_command(VerbAction.ON_LOOK, rendering_service)
    result = command.execute(action_context)
"""

from mudd.commands.base import ActionCommand, ActionContext, ActionResult
from mudd.commands.focus import CloseCommand, OpenCommand
from mudd.commands.inventory import DropCommand, TakeCommand
from mudd.commands.simple import AttackCommand, LookCommand, TouchCommand, UseCommand
from mudd.services.rendering import RenderingService
from mudd.types import VerbAction

__all__ = [
    "ActionCommand",
    "ActionContext",
    "ActionResult",
    "create_command",
    "COMMANDS",
]

COMMANDS: dict[VerbAction, type[ActionCommand]] = {
    VerbAction.ON_LOOK: LookCommand,
    VerbAction.ON_TOUCH: TouchCommand,
    VerbAction.ON_ATTACK: AttackCommand,
    VerbAction.ON_USE: UseCommand,
    VerbAction.ON_TAKE: TakeCommand,
    VerbAction.ON_OPEN: OpenCommand,
    VerbAction.ON_CLOSE: CloseCommand,
    VerbAction.ON_DROP: DropCommand,
}


def create_command(action: VerbAction, rendering: RenderingService) -> ActionCommand:
    """Factory function to create command instances.

    Args:
        action: The verb action type
        rendering: RenderingService for template rendering

    Returns:
        ActionCommand instance for the specified action

    Raises:
        KeyError: If action is not a valid VerbAction
    """
    command_class = COMMANDS[action]
    return command_class(rendering)
