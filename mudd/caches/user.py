"""In-memory cache for user state.

Caches each user's current room and active focus so autocomplete (and
other hot-path lookups) can avoid per-request database queries.

Invalidated instantly on movement and focus changes via a
CacheInvalidationObserver created by ``create_invalidator()``.
Rebuilt in bulk during periodic sync.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import UUID

import asyncpg

from mudd.events import FocusChangedEvent, UserMovedEvent
from mudd.models.user import FOCUS_TIMEOUT_MINUTES, User
from mudd.observers.cache import CacheInvalidationObserver

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UserState:
    """Cached snapshot of a user's room and focus."""

    current_room: str
    focus_id: UUID | None


class UserCache:
    """In-memory cache mapping user IDs to their current state.

    Stores the user's current room and active focus entity instance ID.
    Rebuilt atomically during periodic sync; invalidated per-user on
    movement and focus changes.
    """

    def __init__(self) -> None:
        self._entries: dict[int, UserState] = {}

    def get(self, user_id: int) -> UserState | None:
        """Look up cached state for a user.  Returns None on miss."""
        return self._entries.get(user_id)

    def invalidate(self, user_id: int) -> None:
        """Remove a user's cached state (instant, synchronous)."""
        self._entries.pop(user_id, None)

    async def rebuild_user(self, pool: asyncpg.Pool, user_id: int) -> None:
        """Rebuild cache for a single user after invalidation."""
        room = await User.get_current_room(pool, user_id)
        if room is None:
            self._entries.pop(user_id, None)
            return
        focus_id = await User.get_active_focus_id(pool, user_id, room)
        self._entries[user_id] = UserState(current_room=room, focus_id=focus_id)

    async def rebuild(self, pool: asyncpg.Pool) -> None:
        """Bulk-rebuild cache for all users.

        Uses a single query to fetch user rooms and focus state,
        then swaps the entries dict atomically.
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=FOCUS_TIMEOUT_MINUTES)
        rows = await pool.fetch(
            """
            SELECT u.id,
                   u.current_room,
                   ei.id AS focus_id,
                   uf.updated_at         AS focus_updated_at
            FROM users u
            LEFT JOIN user_focus uf
                ON u.id = uf.user_id
            LEFT JOIN entity_instances ei
                ON uf.entity_instance_id = ei.id
                AND ei.room = u.current_room
            """,
        )

        entries: dict[int, UserState] = {}
        for row in rows:
            focus_id: UUID | None = None
            if row["focus_id"] is not None:
                updated_at = row["focus_updated_at"]
                if updated_at is not None:
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=UTC)
                    if updated_at >= cutoff:
                        focus_id = row["focus_id"]
            entries[row["id"]] = UserState(
                current_room=row["current_room"],
                focus_id=focus_id,
            )

        # Atomic swap
        self._entries = entries
        logger.info("Rebuilt user cache: %d users", len(entries))

    def create_invalidator(self, pool: asyncpg.Pool) -> CacheInvalidationObserver[int]:
        """Create an observer that invalidates this cache on user state changes.

        Hooks into UserMovedEvent (room change) and FocusChangedEvent
        (focus set/cleared).  The returned observer immediately evicts the
        user's entry on notify() and rebuilds it during flush().
        """
        return CacheInvalidationObserver(
            extractors={
                UserMovedEvent: lambda e: e.user_id,
                FocusChangedEvent: lambda e: e.user_id,
            },
            on_invalidate=self.invalidate,
            on_rebuild=partial(self.rebuild_user, pool),
        )
