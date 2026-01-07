"""Verb matcher for fuzzy matching player input to actions."""

import asyncpg

# Similarity threshold for fuzzy matching (0.0 to 1.0)
# 0.5 is a moderate threshold - good balance of typo tolerance and accuracy
SIMILARITY_THRESHOLD = 0.5


async def match_verb(pool: asyncpg.Pool, verb: str) -> str | None:
    """Match a verb to its action using exact or fuzzy matching.

    Args:
        pool: Database connection pool.
        verb: The verb to match (e.g., 'smash', 'smahsh').

    Returns:
        The action name (e.g., 'on_attack') or None if no match found.
    """
    verb = verb.lower().strip()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT action
            FROM verbs
            WHERE verb = $1
               OR similarity(verb, $1) >= $2
            ORDER BY (verb = $1) DESC, similarity(verb, $1) DESC
            LIMIT 1
            """,
            verb,
            SIMILARITY_THRESHOLD,
        )

    if row is None:
        return None

    return row["action"]
