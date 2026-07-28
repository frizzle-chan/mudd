"""Async cached property decorator.

Simplified from https://github.com/ryananguiano/async_property
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, overload


class async_cached_property[T]:
    """Descriptor that caches the result of an async method.

    Usage:
        class MyClass:
            @async_cached_property
            async def expensive_value(self) -> int:
                await asyncio.sleep(1)
                return 42

        obj = MyClass()
        value = await obj.expensive_value  # calls the method
        value = await obj.expensive_value  # returns cached result
    """

    _cache_attr = "__async_cached_property_cache__"
    _lock_attr = "__async_cached_property_lock__"
    _func: Callable[[Any], Coroutine[Any, Any, T]]
    _name: str

    def __init__(self, func: Callable[[Any], Coroutine[Any, Any, T]]) -> None:
        self._func = func
        self._name = getattr(func, "__name__", "<unknown>")
        self.__doc__ = func.__doc__

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name

    @overload
    def __get__(self, instance: None, owner: type) -> "async_cached_property[T]": ...

    @overload
    def __get__(self, instance: object, owner: type) -> Coroutine[Any, Any, T]: ...

    def __get__(
        self, instance: object | None, owner: type
    ) -> "async_cached_property[T] | Coroutine[Any, Any, T]":
        if instance is None:
            return self
        return self._get_value(instance)

    async def _get_value(self, instance: object) -> T:
        cache = self._get_cache(instance)
        if self._name in cache:
            return cache[self._name]

        lock = self._get_lock(instance)
        async with lock:
            # Check again after acquiring lock
            if self._name in cache:
                return cache[self._name]

            value = await self._func(instance)
            cache[self._name] = value
            return value

    def _get_cache(self, instance: object) -> dict[str, Any]:
        cache = getattr(instance, self._cache_attr, None)
        if cache is None:
            cache = {}
            object.__setattr__(instance, self._cache_attr, cache)
        return cache

    def _get_lock(self, instance: object) -> asyncio.Lock:
        locks = getattr(instance, self._lock_attr, None)
        if locks is None:
            locks = {}
            object.__setattr__(instance, self._lock_attr, locks)
        if self._name not in locks:
            locks[self._name] = asyncio.Lock()
        return locks[self._name]
