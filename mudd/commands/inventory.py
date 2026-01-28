"""Inventory-related action commands (take/drop)."""

from mudd.commands.base import ActionCommand
from mudd.services.entity import ResolvedEntity


class TakeCommand(ActionCommand):
    """Command for the 'take' action.

    The actual pickup logic is driven by effects.has_pickup which is
    set when templates call effects.pickup().
    """

    def get_handler_text(self, entity: ResolvedEntity) -> str | None:
        return entity.on_take


class DropCommand(ActionCommand):
    """Command for the 'drop' action.

    The actual drop logic is driven by effects.has_drop which is
    set when templates call effects.drop().
    """

    def get_handler_text(self, entity: ResolvedEntity) -> str | None:
        return entity.on_drop
