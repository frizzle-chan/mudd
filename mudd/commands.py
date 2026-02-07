"""Base types and abstract class for action commands (observer pattern version)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import override

from mudd import template
from mudd.events import EffectsCollector
from mudd.models import IReadableEntity, IRoom, IUser
from mudd.observers import EffectsObserver
from mudd.types import VerbAction
from mudd.views import ActionContext, ViewEntity, ViewUser


@dataclass(slots=True)
class ActionResult:
    """Result of executing an action command.

    Attributes:
        output: The text output to show the user
    """

    output: str


class ActionCommand(ABC):
    """Base class for verb action commands using the observer pattern.

    Each command type implements get_handler_text() to specify which
    entity field to use as the template. Most commands use the default
    execute() which renders the template. Commands with special behavior
    (like open/close) override execute() to add focus signals.

    Unlike the original ActionCommand in mudd/commands/base.py, this version
    uses EffectsObserver rather than returning TriggerEffects directly.
    """

    @abstractmethod
    def get_handler_text(self, entity: IReadableEntity) -> str | None:
        """Get the entity's handler template for this action.

        Args:
            entity: The entity instance being acted upon

        Returns:
            Handler template text, or None if no handler defined
        """
        pass

    async def execute(
        self,
        user: IUser,
        room: IRoom,
        effects: EffectsObserver,
        entity: IReadableEntity,
    ) -> ActionResult:
        """Execute this command.

        Default implementation renders the handler template with full context.
        Override for custom behavior (e.g., focus changes).

        Args:
            user: The user executing the command
            room: The room/context the user is in
            effects: EffectsObserver for collecting side-effect signals
            entity: The entity instance being acted upon

        Returns:
            ActionResult with rendered output
        """
        handler_text = self.get_handler_text(entity)
        if handler_text is None:
            return ActionResult(output="Nothing happens.")

        container_entity = room.current_container
        context = ActionContext(
            e=ViewEntity(entity),
            user=ViewUser(user),
            effects=EffectsCollector(effects),
            container=ViewEntity(container_entity) if container_entity else None,
        )
        output = await template.render(handler_text, context.to_dict())

        return ActionResult(output=output)


class LookCommand(ActionCommand):
    """Command for the 'look' action."""

    @override
    def get_handler_text(self, entity: IReadableEntity) -> str | None:
        """Return the entity's on_look handler template."""
        return entity.entity.on_look


class TouchCommand(ActionCommand):
    """Command for the 'touch' action."""

    @override
    def get_handler_text(self, entity: IReadableEntity) -> str | None:
        """Return the entity's on_touch handler template."""
        return entity.entity.on_touch


class AttackCommand(ActionCommand):
    """Command for the 'attack' action."""

    @override
    def get_handler_text(self, entity: IReadableEntity) -> str | None:
        """Return the entity's on_attack handler template."""
        return entity.entity.on_attack


class UseCommand(ActionCommand):
    """Command for the 'use' action."""

    @override
    def get_handler_text(self, entity: IReadableEntity) -> str | None:
        """Return the entity's on_use handler template."""
        return entity.entity.on_use


class TakeCommand(ActionCommand):
    """Command for the 'take' action."""

    @override
    def get_handler_text(self, entity: IReadableEntity) -> str | None:
        """Return the entity's on_take handler template."""
        return entity.entity.on_take

    @override
    async def execute(
        self,
        user: IUser,
        room: IRoom,
        effects: EffectsObserver,
        entity: IReadableEntity,
    ) -> ActionResult:
        """Execute take command with pickup validation."""
        if not entity.can_pickup:
            return ActionResult(output="You can't take that.")
        if not room.allows_pickup(entity):
            return ActionResult(output="You already have that.")
        return await super().execute(user, room, effects, entity)


class DropCommand(ActionCommand):
    """Command for the 'drop' action."""

    @override
    def get_handler_text(self, entity: IReadableEntity) -> str | None:
        """Return the entity's on_drop handler template."""
        return entity.entity.on_drop

    @override
    async def execute(
        self,
        user: IUser,
        room: IRoom,
        effects: EffectsObserver,
        entity: IReadableEntity,
    ) -> ActionResult:
        """Execute drop command with capability validation."""
        if not entity.can_drop:
            return ActionResult(output="You can't drop that.")
        return await super().execute(user, room, effects, entity)


class OpenCommand(ActionCommand):
    """Command for the 'open' action."""

    @override
    def get_handler_text(self, entity: IReadableEntity) -> str | None:
        """Return the entity's on_open handler template."""
        return entity.entity.on_open

    @override
    async def execute(
        self,
        user: IUser,
        room: IRoom,
        effects: EffectsObserver,
        entity: IReadableEntity,
    ) -> ActionResult:
        """Execute open command with capability validation."""
        if not entity.is_focusable:
            return ActionResult(output="You can't open that.")
        return await super().execute(user, room, effects, entity)


class CloseCommand(ActionCommand):
    """Command for the 'close' action."""

    @override
    def get_handler_text(self, entity: IReadableEntity) -> str | None:
        """Return the entity's on_close handler template."""
        return entity.entity.on_close


class FishCommand(ActionCommand):
    """Command for the 'fish' action."""

    @override
    def get_handler_text(self, entity: IReadableEntity) -> str | None:
        """Return the entity's on_fish handler template."""
        return entity.entity.on_fish


def get_command(action: VerbAction) -> ActionCommand:
    """Get command instance for a verb action."""
    return {
        VerbAction.ON_LOOK: LookCommand(),
        VerbAction.ON_TOUCH: TouchCommand(),
        VerbAction.ON_ATTACK: AttackCommand(),
        VerbAction.ON_USE: UseCommand(),
        VerbAction.ON_TAKE: TakeCommand(),
        VerbAction.ON_DROP: DropCommand(),
        VerbAction.ON_OPEN: OpenCommand(),
        VerbAction.ON_CLOSE: CloseCommand(),
        VerbAction.ON_FISH: FishCommand(),
    }[action]
