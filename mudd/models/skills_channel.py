"""UserSkillsChannel model for tracking per-user Discord skills channels."""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True, slots=True)
class UserSkillsChannel:
    """Model for the user_skills_channels table."""

    user_id: int
    channel_id: int
    category_id: int
    message_id: int | None

    @classmethod
    async def get(cls, pool: asyncpg.Pool, user_id: int) -> UserSkillsChannel | None:
        """Get the skills channel record for a user.

        Args:
            pool: Database connection pool
            user_id: Discord user ID

        Returns:
            UserSkillsChannel or None if not found
        """
        row = await pool.fetchrow(
            """SELECT user_id, channel_id, category_id, message_id
               FROM user_skills_channels
               WHERE user_id = $1""",
            user_id,
        )
        if row is None:
            return None
        return cls(
            user_id=row["user_id"],
            channel_id=row["channel_id"],
            category_id=row["category_id"],
            message_id=row["message_id"],
        )

    @classmethod
    async def create_or_update(
        cls,
        pool: asyncpg.Pool,
        user_id: int,
        channel_id: int,
        category_id: int,
        message_id: int | None = None,
    ) -> None:
        """Insert or update the skills channel record.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
            channel_id: Discord channel ID
            category_id: Discord category ID
            message_id: Discord message ID for the skills overview
        """
        await pool.execute(
            """INSERT INTO user_skills_channels
                   (user_id, channel_id, category_id, message_id)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (user_id) DO UPDATE
                   SET channel_id = $2,
                       category_id = $3,
                       message_id = $4""",
            user_id,
            channel_id,
            category_id,
            message_id,
        )

    @classmethod
    async def update_message_id(
        cls,
        pool: asyncpg.Pool,
        user_id: int,
        message_id: int,
    ) -> None:
        """Update just the message ID for a user's skills channel.

        Args:
            pool: Database connection pool
            user_id: Discord user ID
            message_id: Discord message ID
        """
        await pool.execute(
            """UPDATE user_skills_channels
               SET message_id = $2
               WHERE user_id = $1""",
            user_id,
            message_id,
        )
