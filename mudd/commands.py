"""Base types and abstract class for action commands (observer pattern version)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, override

from mudd import template
from mudd.events import EffectsCollector
from mudd.models import IReadableEntity, IRoom, IUser
from mudd.observers import EffectsObserver
from mudd.types import VerbAction
from mudd.utils import async_cached_property
from mudd.utils.text import RARITY_EMOJI


class ViewEntity:
    """View-friendly wrapper for IReadableEntity that formats output for display."""

    def __init__(self, entity: IReadableEntity):
        self._entity = entity

    def __str__(self) -> str:
        """String representation: name with rarity emoji and markdown bold."""
        return self.name

    @property
    def name(self) -> str:
        """Entity name formatted with rarity emoji and markdown bold."""
        return f"**{self.display_name}**"

    @property
    def display_name(self) -> str:
        """Entity name formatted with rarity emoji"""
        emoji = RARITY_EMOJI[self._entity.rarity]
        return f"{self._entity.name} {emoji}" if emoji else self._entity.name

    @property
    def description_long(self) -> str | None:
        """Long description template."""
        return self._entity.description_long

    @property
    def description_short(self) -> str | None:
        """Short description template."""
        return self._entity.description_short

    @async_cached_property
    async def contents(self) -> str:
        """Get contents as a markdown bullet list."""
        contents = await self._entity.get_contents()
        if not contents:
            return ""
        wrapped = [ViewEntity(item) for item in contents]
        return "\n".join(f"- {item.name}" for item in wrapped)


class ViewUser:
    """View-friendly wrapper for IUser that formats output for display."""

    def __init__(self, user: IUser):
        self._user = user

    def __str__(self) -> str:
        """String representation: Discord mention."""
        return self.mention

    @property
    def mention(self) -> str:
        """Discord mention string for this user."""
        return self._user.mention

    @async_cached_property
    async def balance(self) -> int:
        """User's currency balance."""
        return await self._user.get_balance()


@dataclass(slots=True)
class ActionResult:
    """Result of executing an action command.

    Attributes:
        output: The text output to show the user
    """

    output: str


@dataclass
class ActionContext:
    """Context for executing an action command for passing to action templates."""

    e: ViewEntity
    user: ViewUser
    effects: EffectsCollector
    container: ViewEntity | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for template rendering.

        Note: We don't use asdict() because it tries to recursively copy nested
        objects, which fails for objects with unpicklable attributes.
        """
        return {
            "e": self.e,
            "user": self.user,
            "effects": self.effects,
            "container": self.container,
        }


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
    }[action]
