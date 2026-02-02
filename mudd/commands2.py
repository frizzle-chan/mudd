"""Base types and abstract class for action commands (observer pattern version)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from mudd import template
from mudd.events import EffectsCollector
from mudd.models import IEntityInstance, IUser
from mudd.observers import EffectsObserver
from mudd.scene import Scene
from mudd.utils.text import RARITY_EMOJI


class ViewEntity:
    """View-friendly wrapper for IEntityInstance that formats output for display."""

    def __init__(self, entity: IEntityInstance):
        self._entity = entity

    def __str__(self) -> str:
        """String representation: name with rarity emoji and markdown italics."""
        return self.name

    @property
    def name(self) -> str:
        """Entity name formatted with rarity emoji and markdown italics."""
        emoji = RARITY_EMOJI[self._entity.rarity]
        display_name = f"{self._entity.name} {emoji}" if emoji else self._entity.name
        return f"*{display_name}*"

    @property
    def description_long(self) -> str | None:
        """Long description template."""
        return self._entity.description_long

    @property
    def description_short(self) -> str | None:
        """Short description template."""
        return self._entity.description_short

    @cached_property
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

    @cached_property
    async def balance(self) -> int:
        """User's currency balance."""
        return await self._user.get_balance()


@dataclass
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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for template rendering.

        Note: We don't use asdict() because it tries to recursively copy nested
        objects, which fails for objects with unpicklable attributes.
        """
        return {"e": self.e, "user": self.user, "effects": self.effects}


class ActionCommand(ABC):
    """Base class for verb action commands using the observer pattern.

    Each command type implements get_handler_text() to specify which
    entity field to use as the template. Most commands use the default
    execute() which renders the template. Commands with special behavior
    (like open/close) override execute() to add focus signals.

    Unlike the original ActionCommand in mudd/commands/base.py, this version
    uses EffectsObserver attached to the Scene rather than returning
    TriggerEffects directly.
    """

    @abstractmethod
    def get_handler_text(self, entity: IEntityInstance) -> str | None:
        """Get the entity's handler template for this action.

        Args:
            entity: The entity instance being acted upon

        Returns:
            Handler template text, or None if no handler defined
        """
        pass

    async def execute(self, scene: Scene, entity: IEntityInstance) -> ActionResult:
        """Execute this command.

        Default implementation renders the handler template with full context.
        Override for custom behavior (e.g., focus changes).

        Args:
            scene: Scene with user context and attached observers
            entity: The entity instance being acted upon

        Returns:
            ActionResult with rendered output
        """
        handler_text = self.get_handler_text(entity)
        if handler_text is None:
            return ActionResult(output="Nothing happens.")

        # Get effects observer from scene
        effects = scene.get_observer(EffectsObserver)
        if not effects:
            raise ValueError("EffectsObserver not attached to scene")

        context = ActionContext(
            e=ViewEntity(entity),
            user=ViewUser(scene.user),
            effects=EffectsCollector(effects),
        )
        output = await template.render(handler_text, context.to_dict())

        return ActionResult(output=output)


class LookCommand(ActionCommand):
    """Command for the 'look' action."""

    def get_handler_text(self, entity: IEntityInstance) -> str | None:
        """Return the entity's on_look handler template."""
        return entity.entity.on_look
