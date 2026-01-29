"""Focus context service for modal interactions (ADR 0003).

Manages per-user focus state when interacting with containers and other
focusable entities. Focus is established when a user opens a container
and cleared on room change, timeout, or interaction with unrelated entities.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

from mudd.services.entity import FocusMode

logger = logging.getLogger(__name__)

FOCUS_TIMEOUT_MINUTES = 5


@dataclass(frozen=True)
class FocusContext:
    """Current focus state for a user.

    Focus establishes a "modal" interaction context where autocomplete
    prioritizes entities accessible through the focused entity.

    Note: room is not stored here - it's derived from entity_instances
    when needed. The entity_id field is populated via JOIN with
    entity_instances.
    """

    user_id: int
    instance_id: UUID
    entity_id: str  # From ei.entity_id via join
    entity_name: str
    focus_mode: FocusMode
    updated_at: datetime


class FocusContextService:
    """Manages per-user focus state for modal interactions.

    Focus is established when a user opens a container (or other focusable
    entity) and cleared when they move rooms, interact with unrelated entities,
    or after timeout.

    Usage:
        service = FocusContextService(pool)
        focus = await service.get_focus(user_id, room)
        if focus:
            # Prioritize focused contents in autocomplete
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

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
        row = await self._pool.fetchrow(
            """
            SELECT uf.user_id, uf.instance_id, uf.updated_at,
                   ei.entity_id,
                   re.name AS entity_name, re.focus_mode
            FROM user_focus uf
            JOIN entity_instances ei ON ei.id = uf.instance_id
            JOIN LATERAL resolve_entity(ei.entity_id) re ON TRUE
            WHERE uf.user_id = $1 AND ei.room = $2
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
            await self._pool.execute(
                "DELETE FROM user_focus WHERE user_id = $1", user_id
            )
            logger.debug(f"Cleared stale focus for user {user_id}")
            return None

        return FocusContext(
            user_id=row["user_id"],
            instance_id=row["instance_id"],
            entity_id=row["entity_id"],
            entity_name=row["entity_name"],
            focus_mode=row["focus_mode"],
            updated_at=updated_at,
        )

    async def set_focus(
        self,
        user_id: int,
        instance_id: UUID,
    ) -> str | None:
        """Establish focus on an entity.

        Args:
            user_id: Discord user ID
            instance_id: The entity instance UUID

        Returns:
            Optional message to append to interaction response.
            Returns None (no extra message needed for opening).
        """
        await self._pool.execute(
            """
            INSERT INTO user_focus (user_id, instance_id, updated_at)
            VALUES ($1, $2, now())
            ON CONFLICT (user_id)
            DO UPDATE SET
                instance_id = EXCLUDED.instance_id,
                updated_at = EXCLUDED.updated_at
            """,
            user_id,
            instance_id,
        )
        logger.debug(f"Set focus for user {user_id} on instance {instance_id}")

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
        # Delete focus and get resolved entity info (with prototype inheritance)
        # Uses DELETE USING to join with entity_instances for entity_id
        row = await self._pool.fetchrow(
            """
            DELETE FROM user_focus uf
            USING entity_instances ei
            WHERE uf.user_id = $1 AND uf.instance_id = ei.id
            RETURNING
                ei.entity_id,
                (SELECT on_close FROM resolve_entity(ei.entity_id)) AS on_close
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
        await self._pool.execute(
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

        # Check if entity is contained within the focused entity (check instances)
        row = await self._pool.fetchrow(
            """
            SELECT 1 FROM entity_instances
            WHERE entity_id = $1 AND container_entity_id = $2 AND room = $3
            """,
            entity_id,
            focus.entity_id,
            room,
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

        # Get container contents (query instances, not entity definitions)
        rows = await self._pool.fetch(
            """
            SELECT DISTINCT entity_id FROM entity_instances
            WHERE container_entity_id = $1 AND room = $2
            """,
            focus.entity_id,
            room,
        )

        # Include the focused entity itself and its contents
        entity_ids = [focus.entity_id]
        entity_ids.extend([row["entity_id"] for row in rows])

        return entity_ids
