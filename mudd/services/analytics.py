"""User analytics tracking service."""

from mudd.services.redis import get_redis


async def increment_message_count(user_id: int) -> int:
    """
    Increment the message count for a user.

    Args:
        user_id: The Discord user ID

    Returns:
        The new message count for the user
    """
    client = await get_redis()
    new_count = await client.incr(f"user:{user_id}:message_count")
    return new_count


async def get_message_count(user_id: int) -> int:
    """
    Get the total message count for a user.

    Args:
        user_id: The Discord user ID

    Returns:
        The message count for the user (0 if not set)
    """
    client = await get_redis()
    count = await client.get(f"user:{user_id}:message_count")
    return int(count) if count else 0
