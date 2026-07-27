"""Generic cache invalidation observer.

Provides a reusable observer that maps game events to cache keys,
immediately invalidates those keys, and rebuilds them during flush.

Cache-specific logic (key extraction, invalidation, rebuild) is injected
via constructor parameters, making this observer reusable across different
cache implementations.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Hashable, Mapping
from typing import Any

from mudd.events.types import GameEvent


class CacheInvalidationObserver[K: Hashable]:
    """Observer that invalidates cache entries when game events occur.

    Maps event types to cache key extractors. On ``notify()``, extracts the
    key and calls ``on_invalidate`` synchronously. On ``flush()``, calls
    ``on_rebuild`` for each dirty key asynchronously.

    Type parameter ``K`` is the cache key type (e.g., ``str`` for room IDs).
    """

    flush_priority: int = 0

    def __init__(
        self,
        extractors: Mapping[type, Callable[[Any], K | None]],
        on_invalidate: Callable[[K], None],
        on_rebuild: Callable[[K], Awaitable[None]],
    ) -> None:
        self._extractors = extractors
        self._on_invalidate = on_invalidate
        self._on_rebuild = on_rebuild
        self._dirty: set[K] = set()

    def notify(self, event: GameEvent) -> None:
        """Extract cache key from event and invalidate if matched.

        Unrecognized event types and extractors that return None are ignored.
        """
        extractor = self._extractors.get(type(event))
        if extractor is None:
            return
        key = extractor(event)
        if key is None:
            return
        self._on_invalidate(key)
        self._dirty.add(key)

    async def flush(self) -> list[GameEvent]:
        """Rebuild all dirty cache keys.

        Returns:
            Empty list (no new events produced).
        """
        keys = self._dirty.copy()
        self._dirty.clear()
        for key in keys:
            try:
                await self._on_rebuild(key)
            except Exception:
                self._dirty.add(key)
                raise
        return []

    async def post_flush(self) -> None:
        """No-op — CacheInvalidationObserver has no post-flush work."""
