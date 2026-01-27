"""Simple action commands that just render templates."""

from mudd.commands.base import ActionCommand
from mudd.services.entity import ResolvedEntity


class LookCommand(ActionCommand):
    """Command for the 'look' action."""

    def get_handler_text(self, entity: ResolvedEntity) -> str | None:
        return entity.on_look


class TouchCommand(ActionCommand):
    """Command for the 'touch' action."""

    def get_handler_text(self, entity: ResolvedEntity) -> str | None:
        return entity.on_touch


class AttackCommand(ActionCommand):
    """Command for the 'attack' action."""

    def get_handler_text(self, entity: ResolvedEntity) -> str | None:
        return entity.on_attack


class UseCommand(ActionCommand):
    """Command for the 'use' action."""

    def get_handler_text(self, entity: ResolvedEntity) -> str | None:
        return entity.on_use
