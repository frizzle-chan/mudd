"""Cache implementations.

This package provides in-memory caches that are invalidated via the
CacheInvalidationObserver pattern from mudd.observers.cache.
"""

from mudd.caches.autocomplete import AutocompleteCache
from mudd.caches.user import UserCache

__all__ = [
    "AutocompleteCache",
    "UserCache",
]
