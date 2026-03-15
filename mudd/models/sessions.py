"""Central registry for mutually exclusive modal sessions.

Adding a new modal session type? Add it to _SESSION_TYPES below.
That's the ONE place to update.
"""

from __future__ import annotations

import asyncio

import asyncpg

from mudd.models.dialog import DialogSession
from mudd.models.shop import TradingSession

# Each entry is a session model with a delete(pool, user_id) classmethod
# that returns a session with a thread_id field, or None.
_SESSION_TYPES = [TradingSession, DialogSession]


async def end_all_sessions(pool: asyncpg.Pool, user_id: int) -> list[int]:
    """End all active modal sessions for a user.

    Returns the thread_ids of ended sessions (for cleanup).
    """
    results = await asyncio.gather(
        *(cls.delete(pool, user_id) for cls in _SESSION_TYPES)
    )
    return [session.thread_id for session in results if session is not None]
