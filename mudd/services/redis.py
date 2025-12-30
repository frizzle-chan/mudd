"""Redis client management."""

import os

import redis.asyncio as redis

_pool: redis.ConnectionPool | None = None
_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Get or create the Redis client singleton."""
    global _pool, _client
    if _client is None:
        url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        _pool = redis.ConnectionPool.from_url(url, decode_responses=True)
        _client = redis.Redis(connection_pool=_pool)
    return _client


async def close_redis() -> None:
    """Close Redis connection pool gracefully."""
    global _pool, _client
    if _client:
        await _client.aclose()
    if _pool:
        await _pool.aclose()
    _client = None
    _pool = None
