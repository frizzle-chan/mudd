"""Observer protocol for the effects system."""

from typing import Protocol

from mudd.events.types import GameEvent


class Observer(Protocol):
    """Observer that receives game events.

    Observers are notified synchronously during template rendering
    and flushed asynchronously after the response is sent.
    """

    def notify(self, event: GameEvent) -> None:
        """Receive an event notification.

        Called synchronously during template rendering.

        Args:
            event: The game event to process
        """
        ...

    async def flush(self) -> None:
        """Flush any pending operations.

        Called after the response is sent to execute side effects.
        """
        ...
