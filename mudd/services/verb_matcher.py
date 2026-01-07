"""Verb matcher for fuzzy matching player input to actions."""

import logging

import asyncpg

from mudd.services.verb_action import VerbAction

logger = logging.getLogger(__name__)

# Similarity threshold for fuzzy matching (0.0 to 1.0)
# 0.5 is a moderate threshold - good balance of typo tolerance and accuracy
SIMILARITY_THRESHOLD = 0.5


async def match_verb(pool: asyncpg.Pool, verb: str) -> VerbAction | None:
    """Match a verb to its action using exact or fuzzy matching.

    Uses pg_trgm's % operator with GIN index for efficient fuzzy matching.

    Args:
        pool: Database connection pool.
        verb: The verb to match (e.g., 'smash', 'smassh').

    Returns:
        The VerbAction or None if no match found above threshold.
    """
    verb = verb.lower().strip()

    if not verb:
        return None

    async with pool.acquire() as conn:
        # Set similarity threshold for this connection's % operator
        await conn.execute("SELECT set_limit($1)", SIMILARITY_THRESHOLD)

        row = await conn.fetchrow(
            """
            SELECT action
            FROM verbs
            WHERE verb = $1
               OR verb % $1
            ORDER BY (verb = $1) DESC, similarity(verb, $1) DESC
            LIMIT 1
            """,
            verb,
        )

    if row is None:
        return None

    return VerbAction(row["action"])
