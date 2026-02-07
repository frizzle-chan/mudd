"""Cache implementations.

This package provides in-memory caches that are invalidated via the
CacheInvalidationObserver pattern from mudd.observers.cache.
"""

from mudd.caches.entity_autocomplete import EntityAutocompleteCache
from mudd.caches.user import UserCache

__all__ = [
    "EntityAutocompleteCache",
    "UserCache",
]
