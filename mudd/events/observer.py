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


class OutputObserver(Observer, Protocol):
    """Observer that also produces output text."""

    def get_output(self) -> str:
        """Get the accumulated output text.

        Returns:
            The output text to show the user
        """
        ...
