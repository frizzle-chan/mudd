"""Base types and abstract class for action commands (observer pattern version)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from mudd import view
from mudd.events import EffectsCollector
from mudd.models import IEntityInstance
from mudd.observers import EffectsObserver
from mudd.scene import Scene


@dataclass
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

    def execute(
        self, scene: Scene, entity: IEntityInstance, user_name: str = ""
    ) -> ActionResult:
        """Execute this command.

        Default implementation renders the handler template with full context.
        Override for custom behavior (e.g., focus changes).

        Args:
            scene: Scene with user context and attached observers
            entity: The entity instance being acted upon
            user_name: Display name of the user (from Discord interaction)

        Returns:
            ActionResult with rendered output
        """
        handler_text = self.get_handler_text(entity)
        if handler_text is None:
            return ActionResult(output="Nothing happens.")

        # Get effects observer from scene
        effects = scene.get_observer(EffectsObserver)
        if effects is None:
            # No effects observer attached, render without effects
            context = {
                "e": entity.entity,
                "name": f"*{entity.entity.display_name}*",
                "contents": "",
            }
        else:
            # Create collector and render with effects
            collector = EffectsCollector(effects)
            # Build context with collector for template rendering
            context = {
                "e": entity.entity,
                "name": f"*{entity.entity.display_name}*",
                "contents": "",
                "user": {"name": user_name, "mention": f"<@{scene.user.id}>"},
                "effects": collector,
                "container": None,
                "balance": "",
            }
        output = view.render(handler_text, context)

        return ActionResult(output=output)
