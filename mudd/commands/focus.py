"""Focus-related action commands (open/close)."""

from mudd.commands.base import ActionCommand
from mudd.services.entity import ResolvedEntity


class OpenCommand(ActionCommand):
    """Command for the 'open' action.

    Focus is now controlled by templates via effects.set_focus().
    This command just renders the on_open template.
    """

    def get_handler_text(self, entity: ResolvedEntity) -> str | None:
        return entity.on_open


class CloseCommand(ActionCommand):
    """Command for the 'close' action.

    Focus is now controlled by templates via effects.clear_focus().
    This command just renders the on_close template.
    """

    def get_handler_text(self, entity: ResolvedEntity) -> str | None:
        return entity.on_close
