"""Observer protocol for the effects system."""

from typing import Protocol

from mudd.events.types import GameEvent


class Observer(Protocol):
    """Observer that receives game events.

    Observers are notified synchronously during template rendering
    and flushed asynchronously after the response is sent.

    Attributes:
        flush_priority: Higher values flush first. Default 0.
    """

    flush_priority: int

    def notify(self, event: GameEvent) -> None:
        """Receive an event notification.

        Called synchronously during template rendering.

        Args:
            event: The game event to process
        """
        ...

    async def flush(self) -> list[GameEvent]:
        """Flush any pending operations.

        Called after the response is sent to execute side effects.

        Returns:
            New events produced during flush (e.g. XP results).
        """
        ...

    async def post_flush(self) -> None:
        """Hook called after all flush-produced events are re-broadcast.

        Use for operations that must happen after every observer has
        seen the re-broadcast events (e.g. sending announcements).
        """
        ...
