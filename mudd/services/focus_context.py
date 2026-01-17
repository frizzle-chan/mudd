"""Focus context service for modal interactions (ADR 0003).

Manages per-user focus state when interacting with containers and other
focusable entities. Focus is established when a user opens a container
and cleared on room change, timeout, or interaction with unrelated entities.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from mudd.services.database import get_pool
from mudd.services.entity import FocusMode

if TYPE_CHECKING:
    from mudd.services.entity import ResolvedEntity

logger = logging.getLogger(__name__)

FOCUS_TIMEOUT_MINUTES = 5


@dataclass(frozen=True)
class FocusContext:
    """Current focus state for a user.

    Focus establishes a "modal" interaction context where autocomplete
    prioritizes entities accessible through the focused entity.
    """

    user_id: int
    room: str
    entity_id: str
    entity_name: str
    focus_mode: FocusMode
    updated_at: datetime


class FocusContextService:
    """Manages per-user focus state for modal interactions.

    Focus is established when a user opens a container (or other focusable
    entity) and cleared when they move rooms, interact with unrelated entities,
    or after timeout.

    Usage:
        service = get_focus_context_service()
        focus = await service.get_focus(user_id, room)
        if focus:
            # Prioritize focused contents in autocomplete
    """

    async def get_focus(self, user_id: int, room: str) -> FocusContext | None:
        """Get user's current focus in their current room.

        Returns None if:
        - User has no focus established
        - Focus is in different room (stale)
        - Focus expired (>5 minutes old)

        Stale/expired focus is automatically deleted.

        Args:
            user_id: Discord user ID
            room: Current room name

        Returns:
            Active FocusContext or None
        """
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT uf.user_id, uf.room, uf.entity_id, uf.updated_at,
                   e.name AS entity_name, e.focus_mode
            FROM user_focus uf
            JOIN entities e ON e.id = uf.entity_id
            WHERE uf.user_id = $1 AND uf.room = $2
            """,
            user_id,
            room,
        )

        if not row:
            return None

        # Check if stale (different room check already handled by WHERE clause)
        cutoff = datetime.now(UTC) - timedelta(minutes=FOCUS_TIMEOUT_MINUTES)
        updated_at = row["updated_at"]
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)

        if updated_at < cutoff:
            # Lazy cleanup: delete and return None
            await pool.execute("DELETE FROM user_focus WHERE user_id = $1", user_id)
            logger.debug(f"Cleared stale focus for user {user_id}")
            return None

        return FocusContext(
            user_id=row["user_id"],
            room=row["room"],
            entity_id=row["entity_id"],
            entity_name=row["entity_name"],
            focus_mode=row["focus_mode"],
            updated_at=updated_at,
        )

    async def set_focus(
        self,
        user_id: int,
        room: str,
        entity: "ResolvedEntity",
    ) -> str | None:
        """Establish focus on an entity.

        Args:
            user_id: Discord user ID
            room: Current room name
            entity: The entity to focus on (must have focus_mode != 'none')

        Returns:
            Optional message to append to interaction response.
            Returns None (no extra message needed for opening).
        """
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO user_focus (user_id, room, entity_id, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (user_id)
            DO UPDATE SET
                room = EXCLUDED.room,
                entity_id = EXCLUDED.entity_id,
                updated_at = EXCLUDED.updated_at
            """,
            user_id,
            room,
            entity.id,
        )
        logger.debug(f"Set focus for user {user_id} on {entity.id} in {room}")

        # No extra message needed for establishing focus
        return None

    async def clear_focus(
        self,
        user_id: int,
        reason: str = "interaction",
    ) -> str | None:
        """Clear user's focus.

        Args:
            user_id: Discord user ID
            reason: Why focus was cleared. Options:
                    'interaction', 'movement', 'close', 'timeout'

        Returns:
            Optional message to append to response when closing.
            Returns None for most reasons.
        """
        pool = await get_pool()

        # Delete focus and get resolved entity info (with prototype inheritance)
        row = await pool.fetchrow(
            """
            DELETE FROM user_focus
            WHERE user_id = $1
            RETURNING
                entity_id,
                (SELECT on_close FROM resolve_entity(entity_id)) AS on_close
            """,
            user_id,
        )

        if not row:
            # No focus existed
            return None

        logger.debug(f"Cleared focus for user {user_id} (reason: {reason})")

        # Return close message only for explicit close action
        if reason == "close" and row["on_close"]:
            # Return the template for rendering (not rendered yet)
            return row["on_close"]

        return None

    async def update_focus_timestamp(self, user_id: int) -> None:
        """Update the timestamp on a user's focus to prevent timeout.

        Called when user interacts with focused content.
        """
        pool = await get_pool()
        await pool.execute(
            "UPDATE user_focus SET updated_at = now() WHERE user_id = $1",
            user_id,
        )

    async def is_entity_in_focus(
        self,
        user_id: int,
        room: str,
        entity_id: str,
    ) -> bool:
        """Check if an entity is the focused container or in its contents.

        Used to determine if interacting with entity should preserve focus.

        Args:
            user_id: Discord user ID
            room: Current room name
            entity_id: Entity ID to check

        Returns:
            True if entity is focused or in focused contents
        """
        focus = await self.get_focus(user_id, room)
        if not focus:
            return False

        # Check if entity IS the focused entity
        if entity_id == focus.entity_id:
            return True

        # Check if entity is contained within the focused entity
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT 1 FROM entities
            WHERE id = $1 AND container_id = $2
            """,
            entity_id,
            focus.entity_id,
        )

        return row is not None

    async def get_focused_contents(
        self,
        user_id: int,
        room: str,
    ) -> list[str]:
        """Get entity IDs accessible through current focus (container contents).

        Args:
            user_id: Discord user ID
            room: Current room name

        Returns:
            List of entity IDs (including the focused entity itself),
            or empty list if no focus
        """
        focus = await self.get_focus(user_id, room)
        if not focus:
            return []

        # Get container contents
        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT id FROM entities WHERE container_id = $1",
            focus.entity_id,
        )

        # Include the focused entity itself and its contents
        entity_ids = [focus.entity_id]
        entity_ids.extend([row["id"] for row in rows])

        return entity_ids


# Module-level singleton
_service: FocusContextService | None = None


def is_focus_context_service_initialized() -> bool:
    """Check if the focus context service has been initialized."""
    return _service is not None


def get_focus_context_service() -> FocusContextService:
    """Get the focus context service singleton.

    Raises:
        RuntimeError: If service not initialized (call init_focus_context_service first)
    """
    if _service is None:
        raise RuntimeError("FocusContextService not initialized")
    return _service


def init_focus_context_service() -> FocusContextService:
    """Initialize the focus context service singleton.

    Returns:
        The initialized FocusContextService instance
    """
    global _service
    _service = FocusContextService()
    logger.info("Focus context service initialized")
    return _service
