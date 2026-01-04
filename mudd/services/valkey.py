"""Valkey client management."""

import os
from urllib.parse import urlparse

from glide import (
    GlideClient,
    GlideClientConfiguration,
    NodeAddress,
)

_client: GlideClient | None = None
_wrapper: "ValkeyWrapper | None" = None


class ValkeyWrapper:
    """Wraps GlideClient to provide string-decoded responses."""

    def __init__(self, client: GlideClient):
        self._client = client

    async def get(self, key: str) -> str | None:
        """Get the value of a key, decoded as UTF-8 string."""
        result = await self._client.get(key)
        return result.decode("utf-8") if result else None

    async def set(self, key: str, value: str) -> str | None:
        """Set key to hold the string value."""
        result = await self._client.set(key, value)
        return result.decode("utf-8") if result else None

    async def delete(self, key: str) -> int:
        """Delete a key. Returns the number of keys removed (0 or 1)."""
        return await self._client.delete([key])


async def get_valkey() -> ValkeyWrapper:
    """Get or create the Valkey client singleton."""
    global _client, _wrapper
    if _wrapper is None:
        url = os.environ.get("VALKEY_URL", "valkey://localhost:6379")
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379

        config = GlideClientConfiguration(
            addresses=[NodeAddress(host, port)],
            request_timeout=5000,
        )
        _client = await GlideClient.create(config)
        _wrapper = ValkeyWrapper(_client)
    return _wrapper


async def close_valkey() -> None:
    """Close Valkey connection gracefully."""
    global _client, _wrapper
    if _client:
        await _client.close()
    _client = None
    _wrapper = None
