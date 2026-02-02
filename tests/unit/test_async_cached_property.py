"""Tests for async_cached_property decorator."""

import asyncio

import pytest

from mudd.utils import async_cached_property


class TestAsyncCachedProperty:
    """Tests for async_cached_property decorator."""

    @pytest.mark.asyncio
    async def test_caches_result(self):
        """Property is only computed once."""
        call_count = 0

        class MyClass:
            @async_cached_property
            async def value(self) -> int:
                nonlocal call_count
                call_count += 1
                return 42

        obj = MyClass()
        assert await obj.value == 42
        assert await obj.value == 42
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_separate_instances_have_separate_caches(self):
        """Each instance has its own cached value."""
        call_count = 0

        class MyClass:
            def __init__(self, val: int):
                self._val = val

            @async_cached_property
            async def value(self) -> int:
                nonlocal call_count
                call_count += 1
                return self._val

        obj1 = MyClass(1)
        obj2 = MyClass(2)

        assert await obj1.value == 1
        assert await obj2.value == 2
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_access_only_computes_once(self):
        """Concurrent awaits only compute the value once."""
        call_count = 0

        class MyClass:
            @async_cached_property
            async def value(self) -> int:
                nonlocal call_count
                call_count += 1
                await asyncio.sleep(0.01)
                return 42

        obj = MyClass()
        results = await asyncio.gather(obj.value, obj.value, obj.value)

        assert results == [42, 42, 42]
        assert call_count == 1

    def test_class_access_returns_descriptor(self):
        """Accessing on the class returns the descriptor itself."""

        class MyClass:
            @async_cached_property
            async def value(self) -> int:
                return 42

        assert isinstance(MyClass.value, async_cached_property)
