"""Focus clearing observer that clears focus when users move rooms."""

from __future__ import annotations

import logging

import asyncpg

from mudd.events import GameEvent, UserMovedEvent

logger = logging.getLogger(__name__)


class FocusClearingObserver:
    """Observer that clears user focus when they move rooms.

    Per ADR 0003, focus is cleared when a user moves to a different room.
    This observer handles that behavior by listening for UserMovedEvent.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Initialize the focus clearing observer.

        Args:
            pool: Database connection pool
        """
        self._pool = pool
        self._pending_clears: list[int] = []

    def notify(self, event: GameEvent) -> None:
        """Queue focus clear for moved users.

        Args:
            event: The game event to process
        """
        match event:
            case UserMovedEvent(user_id=user_id):
                self._pending_clears.append(user_id)

    async def flush(self) -> None:
        """Clear focus for all users who moved.

        This is called after the command response is sent.
        """
        pending = self._pending_clears
        self._pending_clears = []

        for user_id in pending:
            try:
                # Note: We don't execute on_close templates here since movement
                # isn't the same as explicitly closing a container.
                await self._pool.execute(
                    "DELETE FROM user_focus WHERE user_id = $1",
                    user_id,
                )
                logger.debug(f"Cleared focus for user {user_id} due to movement")
            except Exception:
                logger.exception(f"Failed to clear focus for user {user_id}")
