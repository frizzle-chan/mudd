"""Unit tests for UserCache."""

from __future__ import annotations

from uuid import uuid4

from mudd.caches.user import UserCache, UserState
from mudd.events import FocusChangedEvent, UserMovedEvent
from mudd.observers.cache import CacheInvalidationObserver


class TestUserState:
    """Tests for the UserState dataclass."""

    def test_with_focus(self):
        uid = uuid4()
        state = UserState(current_room="lobby", focus_id=uid)
        assert state.current_room == "lobby"
        assert state.focus_id == uid

    def test_without_focus(self):
        state = UserState(current_room="lobby", focus_id=None)
        assert state.focus_id is None


class TestGetAndInvalidate:
    """Tests for UserCache.get() and .invalidate()."""

    def test_empty_cache_returns_none(self):
        cache = UserCache()
        assert cache.get(12345) is None

    def test_hit_after_manual_insert(self):
        cache = UserCache()
        state = UserState(current_room="lobby", focus_id=None)
        cache._entries[12345] = state
        assert cache.get(12345) is state

    def test_invalidate_removes_entry(self):
        cache = UserCache()
        cache._entries[12345] = UserState(current_room="lobby", focus_id=None)
        cache.invalidate(12345)
        assert cache.get(12345) is None

    def test_invalidate_nonexistent_is_noop(self):
        cache = UserCache()
        cache.invalidate(99999)  # Should not raise

    def test_miss_for_different_user(self):
        cache = UserCache()
        cache._entries[12345] = UserState(current_room="lobby", focus_id=None)
        assert cache.get(99999) is None


class TestCreateInvalidator:
    """Tests for UserCache.create_invalidator() factory."""

    def test_returns_cache_invalidation_observer(self):
        cache = UserCache()
        result = cache.create_invalidator(None)  # ty: ignore[invalid-argument-type]
        assert isinstance(result, CacheInvalidationObserver)

    def test_invalidates_on_user_moved(self):
        cache = UserCache()
        cache._entries[42] = UserState(current_room="lobby", focus_id=None)
        cache._entries[99] = UserState(current_room="garden", focus_id=None)

        invalidator = cache.create_invalidator(None)  # ty: ignore[invalid-argument-type]
        invalidator.notify(
            UserMovedEvent(user_id=42, from_room="lobby", to_room="garden", guild_id=1)
        )

        assert cache.get(42) is None
        assert cache.get(99) is not None

    def test_invalidates_on_focus_changed(self):
        cache = UserCache()
        cache._entries[42] = UserState(current_room="lobby", focus_id=uuid4())

        invalidator = cache.create_invalidator(None)  # ty: ignore[invalid-argument-type]
        invalidator.notify(FocusChangedEvent(user_id=42))

        assert cache.get(42) is None
