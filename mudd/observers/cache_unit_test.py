"""Unit tests for CacheInvalidationObserver."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mudd.observers.cache import CacheInvalidationObserver


# Minimal event types for testing — no dependency on real game events.
@dataclass(frozen=True, slots=True)
class FakeEventA:
    key: str


@dataclass(frozen=True, slots=True)
class FakeEventB:
    key: str


@dataclass(frozen=True, slots=True)
class UnhandledEvent:
    pass


async def _noop_rebuild(_key: str) -> None:
    """Async no-op for tests that never reach a rebuild."""


def _make_observer(
    invalidated: list[str],
    rebuilt: list[str],
) -> CacheInvalidationObserver[str]:
    """Create an observer with extractors for FakeEventA and FakeEventB."""

    async def on_rebuild(key: str) -> None:
        rebuilt.append(key)

    return CacheInvalidationObserver(
        extractors={
            FakeEventA: lambda e: e.key,
            FakeEventB: lambda e: e.key,
        },
        on_invalidate=invalidated.append,
        on_rebuild=on_rebuild,
    )


class TestNotify:
    """Tests for CacheInvalidationObserver.notify()."""

    def test_calls_on_invalidate_for_matched_event(self):
        invalidated: list[str] = []
        observer = _make_observer(invalidated, [])

        observer.notify(FakeEventA(key="room-1"))  # ty: ignore[invalid-argument-type]

        assert invalidated == ["room-1"]

    def test_ignores_unhandled_event_type(self):
        invalidated: list[str] = []
        observer = _make_observer(invalidated, [])

        observer.notify(UnhandledEvent())  # ty: ignore[invalid-argument-type]

        assert invalidated == []

    def test_ignores_none_key_from_extractor(self):
        invalidated: list[str] = []

        observer = CacheInvalidationObserver(
            extractors={FakeEventA: lambda _: None},
            on_invalidate=invalidated.append,
            on_rebuild=_noop_rebuild,
        )

        observer.notify(FakeEventA(key="x"))  # ty: ignore[invalid-argument-type]

        assert invalidated == []

    def test_multiple_events_invalidate_multiple_keys(self):
        invalidated: list[str] = []
        observer = _make_observer(invalidated, [])

        observer.notify(FakeEventA(key="room-1"))  # ty: ignore[invalid-argument-type]
        observer.notify(FakeEventB(key="room-2"))  # ty: ignore[invalid-argument-type]

        assert invalidated == ["room-1", "room-2"]

    def test_duplicate_keys_invalidate_each_time(self):
        """Each notify calls on_invalidate even for duplicate keys."""
        invalidated: list[str] = []
        observer = _make_observer(invalidated, [])

        observer.notify(FakeEventA(key="room-1"))  # ty: ignore[invalid-argument-type]
        observer.notify(FakeEventA(key="room-1"))  # ty: ignore[invalid-argument-type]

        assert invalidated == ["room-1", "room-1"]


class TestFlush:
    """Tests for CacheInvalidationObserver.flush()."""

    @pytest.mark.asyncio
    async def test_rebuilds_dirty_keys(self):
        rebuilt: list[str] = []
        observer = _make_observer([], rebuilt)

        observer.notify(FakeEventA(key="room-1"))  # ty: ignore[invalid-argument-type]
        await observer.flush()

        assert rebuilt == ["room-1"]

    @pytest.mark.asyncio
    async def test_deduplicates_dirty_keys(self):
        """Multiple events for the same key only trigger one rebuild."""
        rebuilt: list[str] = []
        observer = _make_observer([], rebuilt)

        observer.notify(FakeEventA(key="room-1"))  # ty: ignore[invalid-argument-type]
        observer.notify(FakeEventA(key="room-1"))  # ty: ignore[invalid-argument-type]
        await observer.flush()

        assert rebuilt == ["room-1"]

    @pytest.mark.asyncio
    async def test_clears_dirty_set_after_flush(self):
        rebuilt: list[str] = []
        observer = _make_observer([], rebuilt)

        observer.notify(FakeEventA(key="room-1"))  # ty: ignore[invalid-argument-type]
        await observer.flush()
        rebuilt.clear()

        # Second flush should be a no-op
        await observer.flush()
        assert rebuilt == []

    @pytest.mark.asyncio
    async def test_flush_with_no_events_is_noop(self):
        rebuilt: list[str] = []
        observer = _make_observer([], rebuilt)

        await observer.flush()

        assert rebuilt == []

    @pytest.mark.asyncio
    async def test_rebuilds_multiple_keys(self):
        rebuilt: list[str] = []
        observer = _make_observer([], rebuilt)

        observer.notify(FakeEventA(key="room-1"))  # ty: ignore[invalid-argument-type]
        observer.notify(FakeEventB(key="room-2"))  # ty: ignore[invalid-argument-type]
        await observer.flush()

        assert sorted(rebuilt) == ["room-1", "room-2"]
