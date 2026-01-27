"""Focus-related action commands (open/close)."""

from mudd.commands.base import ActionCommand, ActionContext, ActionResult
from mudd.services.entity import ResolvedEntity


class OpenCommand(ActionCommand):
    """Command for the 'open' action.

    When opening a focusable entity (e.g., container), signals that
    focus should be established on that entity.
    """

    def get_handler_text(self, entity: ResolvedEntity) -> str | None:
        return entity.on_open

    def execute(self, ctx: ActionContext) -> ActionResult:
        result = super().execute(ctx)
        # Signal focus should be set if entity supports it
        if ctx.entity.focus_mode != "none":
            return ActionResult(
                output=result.output,
                effects=result.effects,
                set_focus=ctx.entity,
            )
        return result


class CloseCommand(ActionCommand):
    """Command for the 'close' action.

    Signals that focus should be cleared after execution.
    """

    def get_handler_text(self, entity: ResolvedEntity) -> str | None:
        return entity.on_close

    def execute(self, ctx: ActionContext) -> ActionResult:
        result = super().execute(ctx)
        return ActionResult(
            output=result.output,
            effects=result.effects,
            clear_focus=True,
        )
