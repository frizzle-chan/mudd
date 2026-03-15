"""Dialog session model for NPC dialog tree interactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(frozen=True, slots=True)
class DialogSession:
    """An active dialog session between a user and an NPC."""

    user_id: int
    dialog_id: str
    thread_id: int
    created_at: datetime

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> DialogSession:
        """Construct DialogSession from asyncpg.Record."""
        return cls(
            user_id=row["user_id"],
            dialog_id=row["dialog_id"],
            thread_id=row["thread_id"],
            created_at=row["created_at"],
        )

    @classmethod
    async def get(cls, pool: asyncpg.Pool, user_id: int) -> DialogSession | None:
        """Fetch the active dialog session for a user.

        Args:
            pool: Database connection pool
            user_id: The user to look up

        Returns:
            DialogSession instance, or None if no active session
        """
        row = await pool.fetchrow(
            "SELECT * FROM user_dialog_sessions WHERE user_id = $1",
            user_id,
        )
        if row is None:
            return None
        return cls._from_row(row)

    @classmethod
    async def create(
        cls,
        pool: asyncpg.Pool,
        user_id: int,
        dialog_id: str,
        thread_id: int,
    ) -> DialogSession:
        """Create a new dialog session.

        Callers must end any existing session first.

        Args:
            pool: Database connection pool
            user_id: The user starting the session
            dialog_id: The dialog tree being interacted with
            thread_id: Discord thread for this session

        Returns:
            The newly created DialogSession
        """
        row = await pool.fetchrow(
            """
            INSERT INTO user_dialog_sessions (user_id, dialog_id, thread_id)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            user_id,
            dialog_id,
            thread_id,
        )
        assert row is not None
        return cls._from_row(row)

    @classmethod
    async def delete(cls, pool: asyncpg.Pool, user_id: int) -> DialogSession | None:
        """Delete the active dialog session for a user.

        Returns the deleted session so callers can clean up the
        Discord thread. No-op if no session exists.

        Args:
            pool: Database connection pool
            user_id: The user whose session to end

        Returns:
            The deleted DialogSession, or None if no session existed
        """
        row = await pool.fetchrow(
            "DELETE FROM user_dialog_sessions WHERE user_id = $1 RETURNING *",
            user_id,
        )
        if row is None:
            return None
        return cls._from_row(row)
