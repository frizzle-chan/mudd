"""User model with database access methods."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from mudd.models.entity import EntityInstance
    from mudd.models.room import Room

from mudd.models.entity import FocusMode

FOCUS_TIMEOUT_MINUTES = 5


@dataclass(frozen=True)
class FocusContext:
    """Value object representing a user's current focus state.

    Focus establishes a "modal" interaction context where autocomplete
    prioritizes entities accessible through the focused entity.

    This is a pure value object with no database access methods.
    """

    entity_id: str
    entity_name: str
    focus_mode: FocusMode
    updated_at: datetime


@dataclass(frozen=True)
class User:
    """User model with database access methods.

    Instances are immutable. Mutation methods (move_to) update the
    database and return new instances.
    """

    id: int
    current_room: str
    _pool: asyncpg.Pool = field(repr=False, compare=False)

    @classmethod
    async def get(cls, pool: asyncpg.Pool, user_id: int) -> User | None:
        """Get user by Discord ID.

        Args:
            pool: Database connection pool
            user_id: Discord user snowflake ID

        Returns:
            User model instance, or None if not found
        """
        row = await pool.fetchrow(
            "SELECT id, current_room FROM users WHERE id = $1",
            user_id,
        )

        if row is None:
            return None

        return cls(
            id=row["id"],
            current_room=row["current_room"],
            _pool=pool,
        )

    @classmethod
    async def get_or_create(cls, pool: asyncpg.Pool, user_id: int) -> User:
        """Get user by Discord ID, creating with default room if missing.

        Args:
            pool: Database connection pool
            user_id: Discord user snowflake ID

        Returns:
            User model instance (existing or newly created)
        """
        row = await pool.fetchrow(
            """
            INSERT INTO users (id, current_room)
            SELECT $1, r.id FROM rooms r WHERE r.is_default = TRUE
            ON CONFLICT (id) DO UPDATE SET id = EXCLUDED.id
            RETURNING id, current_room
            """,
            user_id,
        )

        if row is None:
            # Fallback: no default room configured, try to get existing user
            existing = await cls.get(pool, user_id)
            if existing:
                return existing
            raise ValueError("No default room configured and user does not exist")

        return cls(
            id=row["id"],
            current_room=row["current_room"],
            _pool=pool,
        )

    async def get_room(self) -> Room:
        """Get the user's current room.

        Returns:
            Room model instance

        Raises:
            ValueError: If room not found (should never happen with FK constraint)
        """
        from mudd.models.room import Room

        room = await Room.get(self._pool, self.current_room)
        if room is None:
            raise ValueError(f"Room not found: {self.current_room}")
        return room

    async def get_inventory(self) -> list[EntityInstance]:
        """Get all entities in the user's inventory.

        Returns:
            List of EntityInstance objects owned by this user
        """
        from mudd.models.entity import EntityInstance

        return await EntityInstance.get_by_owner(self._pool, self.id)

    async def get_focus(self) -> FocusContext | None:
        """Get the user's current focus context, if any.

        Returns None if:
        - User has no focus established
        - Focus is in different room (stale)
        - Focus expired (>5 minutes old)

        Stale/expired focus is automatically deleted.

        Returns:
            Active FocusContext or None
        """
        row = await self._pool.fetchrow(
            """
            SELECT uf.entity_id, uf.updated_at,
                   re.name AS entity_name, re.focus_mode
            FROM user_focus uf
            JOIN LATERAL resolve_entity(uf.entity_id) re ON TRUE
            WHERE uf.user_id = $1 AND uf.room = $2
            """,
            self.id,
            self.current_room,
        )

        if not row:
            return None

        # Check timeout
        cutoff = datetime.now(UTC) - timedelta(minutes=FOCUS_TIMEOUT_MINUTES)
        updated_at = row["updated_at"]
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)

        if updated_at < cutoff:
            # Lazy cleanup: delete and return None
            await self._pool.execute(
                "DELETE FROM user_focus WHERE user_id = $1", self.id
            )
            return None

        return FocusContext(
            entity_id=row["entity_id"],
            entity_name=row["entity_name"],
            focus_mode=row["focus_mode"],
            updated_at=updated_at,
        )

    async def set_focus(self, entity_id: str) -> None:
        """Establish focus on an entity.

        Args:
            entity_id: The entity ID to focus on
        """
        await self._pool.execute(
            """
            INSERT INTO user_focus (user_id, room, entity_id, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (user_id)
            DO UPDATE SET
                room = EXCLUDED.room,
                entity_id = EXCLUDED.entity_id,
                updated_at = EXCLUDED.updated_at
            """,
            self.id,
            self.current_room,
            entity_id,
        )

    async def clear_focus(self) -> str | None:
        """Clear user's focus.

        Returns:
            The on_close template if the focused entity has one, else None
        """
        row = await self._pool.fetchrow(
            """
            DELETE FROM user_focus
            WHERE user_id = $1
            RETURNING
                entity_id,
                (SELECT on_close FROM resolve_entity(entity_id)) AS on_close
            """,
            self.id,
        )

        if not row:
            return None

        return row["on_close"]

    async def refresh_focus(self) -> None:
        """Update the timestamp on user's focus to prevent timeout."""
        await self._pool.execute(
            "UPDATE user_focus SET updated_at = now() WHERE user_id = $1",
            self.id,
        )

    async def get_focused_contents(self) -> list[str]:
        """Get entity IDs accessible through current focus (container contents).

        Returns:
            List of entity IDs (including the focused entity itself),
            or empty list if no focus
        """
        focus = await self.get_focus()
        if not focus:
            return []

        rows = await self._pool.fetch(
            """
            SELECT DISTINCT entity_id FROM entity_instances
            WHERE container_entity_id = $1 AND room = $2
            """,
            focus.entity_id,
            self.current_room,
        )

        entity_ids = [focus.entity_id]
        entity_ids.extend([row["entity_id"] for row in rows])

        return entity_ids

    async def get_balance(self) -> int:
        """Get the user's currency balance.

        Returns:
            Balance in yen (0 if no account exists)
        """
        row = await self._pool.fetchrow(
            "SELECT balance FROM currency_accounts WHERE user_id = $1",
            self.id,
        )

        if row is None:
            return 0

        return row["balance"]

    async def move_to(self, room_id: str) -> User:
        """Move the user to a different room.

        Updates the database and returns a new User instance.

        Args:
            room_id: Target room ID

        Returns:
            New User instance with updated location
        """
        await self._pool.execute(
            "UPDATE users SET current_room = $2 WHERE id = $1",
            self.id,
            room_id,
        )

        return replace(self, current_room=room_id)
