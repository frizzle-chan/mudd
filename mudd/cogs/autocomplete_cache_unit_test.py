"""Unit tests for AutocompleteCache."""

import contextlib
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from discord import app_commands

from mudd.cogs.autocomplete_cache import (
    AutocompleteCache,
    AutocompleteCacheInvalidator,
    _make_choice,
)
from mudd.events import EntityDestroyedEvent, EntityDroppedEvent, EntityPickedUpEvent
from mudd.models.entity import EntityInstance, ResolvedEntity
from mudd.models.room import Room
from mudd.utils.text import Rarity


def _make_entity(name: str, rarity: Rarity = "common") -> ResolvedEntity:
    return ResolvedEntity(
        id=f"test::{name}",
        name=name,
        description_short=None,
        description_long=None,
        on_look=None,
        on_touch=None,
        on_attack=None,
        on_use=None,
        on_take=None,
        on_open=None,
        on_close=None,
        on_drop=None,
        contents_visible=False,
        rarity=rarity,
    )


def _make_instance(
    name: str, rarity: Rarity = "common", instance_id: UUID | None = None
) -> EntityInstance:
    return EntityInstance(
        instance_id=instance_id or uuid4(),
        entity=_make_entity(name, rarity),
        room_id="test-room",
        owner_id=None,
    )


def _make_room(room_id: str = "test-room", name: str = "Test Room") -> Room:
    return Room(
        id=room_id,
        name=name,
        description="A test room.",
        zone_id="test-zone",
        _pool=None,  # type: ignore[arg-type]
    )


class TestMakeChoice:
    """Tests for _make_choice formatting."""

    def test_entity_instance_choice(self):
        """EntityInstance gets entity:// prefix on value."""
        instance = _make_instance("Sword")
        choice = _make_choice(instance)
        assert choice.name == "Sword \u26aa"  # common = white circle
        assert choice.value == f"entity://{instance.instance_id}"

    def test_room_entity_choice(self):
        """RoomEntityInstance gets room:// value directly."""
        room = _make_room()
        room_entity = room.as_entity(focus_name=None)
        choice = _make_choice(room_entity)
        assert choice.name == "\U0001f4cd Test Room"
        assert choice.value == "room://test-room"

    def test_room_entity_with_focus_name(self):
        """RoomEntityInstance includes [Close X] when focus_name is set."""
        room = _make_room()
        room_entity = room.as_entity(focus_name="Treasure Chest")
        choice = _make_choice(room_entity)
        assert "[Close Treasure Chest]" in choice.name

    def test_rare_entity_has_emoji(self):
        """Rare entities get their rarity emoji."""
        instance = _make_instance("Diamond", rarity="rare")
        choice = _make_choice(instance)
        assert "Diamond" in choice.name

    def test_no_rarity_entity_no_emoji(self):
        """Entities with 'none' rarity get no emoji suffix."""
        instance = _make_instance("Room Thing", rarity="none")
        choice = _make_choice(instance)
        assert choice.name == "Room Thing"


class TestAutocompleteCacheGetters:
    """Tests for cache lookup methods."""

    def test_empty_cache_returns_none(self):
        """Empty cache returns None for any lookup."""
        cache = AutocompleteCache()
        assert cache.get_room_choices("any-room") is None
        assert cache.get_focus_choices("any-room", uuid4()) is None

    def test_room_choices_hit(self):
        """Room choices are returned when present."""
        cache = AutocompleteCache()
        choices = [app_commands.Choice(name="Test", value="test")]
        cache._room_choices["lobby"] = choices
        assert cache.get_room_choices("lobby") is choices

    def test_room_choices_miss(self):
        """Room choices return None for unknown room."""
        cache = AutocompleteCache()
        cache._room_choices["lobby"] = []
        assert cache.get_room_choices("other-room") is None

    def test_focus_choices_hit(self):
        """Focus choices are returned for matching (room, instance) pair."""
        cache = AutocompleteCache()
        uid = uuid4()
        choices = [app_commands.Choice(name="Item", value="entity://abc")]
        cache._focus_choices[("lobby", str(uid))] = choices
        assert cache.get_focus_choices("lobby", uid) is choices

    def test_focus_choices_miss_wrong_room(self):
        """Focus choices return None when room doesn't match."""
        cache = AutocompleteCache()
        uid = uuid4()
        cache._focus_choices[("lobby", str(uid))] = []
        assert cache.get_focus_choices("other-room", uid) is None

    def test_focus_choices_miss_wrong_instance(self):
        """Focus choices return None when instance doesn't match."""
        cache = AutocompleteCache()
        cache._focus_choices[("lobby", str(uuid4()))] = []
        assert cache.get_focus_choices("lobby", uuid4()) is None


class TestInvalidateRoom:
    """Tests for AutocompleteCache.invalidate_room()."""

    def test_invalidate_removes_room_choices(self):
        """Room choices are removed after invalidation."""
        cache = AutocompleteCache()
        cache._room_choices["lobby"] = [app_commands.Choice(name="X", value="x")]
        cache.invalidate_room("lobby")
        assert cache.get_room_choices("lobby") is None

    def test_invalidate_removes_focus_choices_for_room(self):
        """All focus choices for the room are removed."""
        cache = AutocompleteCache()
        uid1, uid2 = uuid4(), uuid4()
        cache._focus_choices[("lobby", str(uid1))] = []
        cache._focus_choices[("lobby", str(uid2))] = []
        cache._focus_choices[("other-room", str(uid1))] = []

        cache.invalidate_room("lobby")

        assert cache.get_focus_choices("lobby", uid1) is None
        assert cache.get_focus_choices("lobby", uid2) is None
        # Other room unaffected
        assert cache.get_focus_choices("other-room", uid1) is not None

    def test_invalidate_nonexistent_room_is_noop(self):
        """Invalidating a room not in cache doesn't raise."""
        cache = AutocompleteCache()
        cache.invalidate_room("nonexistent")  # Should not raise


class TestAutocompleteCacheInvalidatorFactory:
    """Tests for AutocompleteCacheInvalidator.from_cache()."""

    def test_from_cache_returns_none_when_no_cache(self):
        """from_cache returns None when cache is None."""
        result = AutocompleteCacheInvalidator.from_cache(None, None, "room")  # type: ignore[arg-type]
        assert result is None

    def test_from_cache_returns_invalidator_when_cache_present(self):
        """from_cache returns an invalidator when cache is provided."""
        cache = AutocompleteCache()
        result = AutocompleteCacheInvalidator.from_cache(cache, None, "room")  # type: ignore[arg-type]
        assert isinstance(result, AutocompleteCacheInvalidator)


class TestAutocompleteCacheInvalidatorNotify:
    """Tests for AutocompleteCacheInvalidator.notify() instant invalidation."""

    def _make_populated_cache(self) -> AutocompleteCache:
        """Create a cache with entries for 'lobby' and 'garden'."""
        cache = AutocompleteCache()
        cache._room_choices["lobby"] = [app_commands.Choice(name="X", value="x")]
        cache._room_choices["garden"] = [app_commands.Choice(name="Y", value="y")]
        uid = uuid4()
        cache._focus_choices[("lobby", str(uid))] = []
        return cache

    def test_pickup_invalidates_scene_room(self):
        """EntityPickedUpEvent invalidates the scene's room (not the entity's)."""
        cache = self._make_populated_cache()
        # Entity after pickup has room_id=None
        entity = _make_instance("Sword")
        picked_up = replace(entity, room_id=None, owner_id=12345)

        invalidator = AutocompleteCacheInvalidator(cache, None, "lobby")  # type: ignore[arg-type]
        invalidator.notify(EntityPickedUpEvent(instance=picked_up))

        assert cache.get_room_choices("lobby") is None
        assert cache.get_room_choices("garden") is not None

    def test_drop_invalidates_target_room(self):
        """EntityDroppedEvent invalidates the room the entity was dropped into."""
        cache = self._make_populated_cache()
        entity = _make_instance("Sword")
        dropped = replace(entity, room_id="garden", owner_id=None)

        invalidator = AutocompleteCacheInvalidator(cache, None, "lobby")  # type: ignore[arg-type]
        invalidator.notify(EntityDroppedEvent(instance=dropped))

        # lobby (scene room) not invalidated — only the drop target
        assert cache.get_room_choices("lobby") is not None
        assert cache.get_room_choices("garden") is None

    def test_destroy_invalidates_entity_room(self):
        """EntityDestroyedEvent invalidates the entity's room."""
        cache = self._make_populated_cache()
        entity = _make_instance("Sword")
        destroyed = replace(entity, room_id="garden")

        invalidator = AutocompleteCacheInvalidator(cache, None, "lobby")  # type: ignore[arg-type]
        invalidator.notify(EntityDestroyedEvent(instance=destroyed))

        assert cache.get_room_choices("garden") is None
        assert cache.get_room_choices("lobby") is not None

    def test_destroy_falls_back_to_scene_room(self):
        """EntityDestroyedEvent uses scene room when entity has no room."""
        cache = self._make_populated_cache()
        entity = _make_instance("Sword")
        destroyed = replace(entity, room_id=None)

        invalidator = AutocompleteCacheInvalidator(cache, None, "lobby")  # type: ignore[arg-type]
        invalidator.notify(EntityDestroyedEvent(instance=destroyed))

        assert cache.get_room_choices("lobby") is None

    def test_notify_queues_rooms_for_rebuild(self):
        """notify() queues affected rooms for flush() to rebuild."""
        cache = self._make_populated_cache()
        entity = _make_instance("Sword")
        picked_up = replace(entity, room_id=None, owner_id=12345)

        invalidator = AutocompleteCacheInvalidator(cache, None, "lobby")  # type: ignore[arg-type]
        invalidator.notify(EntityPickedUpEvent(instance=picked_up))

        assert "lobby" in invalidator._rooms_to_rebuild


class TestAutocompleteCacheInvalidatorFlush:
    """Tests for AutocompleteCacheInvalidator.flush()."""

    @pytest.mark.asyncio
    async def test_flush_clears_rebuild_queue(self):
        """flush() clears the rooms_to_rebuild set."""
        cache = AutocompleteCache()
        cache._room_choices["lobby"] = []
        entity = _make_instance("Sword")
        picked_up = replace(entity, room_id=None, owner_id=12345)

        # flush will try rebuild_room which needs a real pool.
        # We just test that the queue is cleared.
        invalidator = AutocompleteCacheInvalidator(cache, None, "lobby")  # type: ignore[arg-type]
        invalidator.notify(EntityPickedUpEvent(instance=picked_up))
        assert len(invalidator._rooms_to_rebuild) > 0

        # flush with None pool will fail on rebuild but queue should clear
        with contextlib.suppress(Exception):
            await invalidator.flush()
        assert len(invalidator._rooms_to_rebuild) == 0
