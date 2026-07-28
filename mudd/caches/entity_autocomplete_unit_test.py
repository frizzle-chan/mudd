"""Unit tests for EntityAutocompleteCache."""

from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

import asyncpg
from discord import app_commands

from mudd.caches.entity_autocomplete import (
    EntityAutocompleteCache,
    _make_choice,
    entities_to_choices,
)
from mudd.events import EntityPickedUpEvent
from mudd.models.entity import EntityInstance, ResolvedEntity
from mudd.models.room import Room
from mudd.observers.cache import CacheInvalidationObserver
from mudd.utils.text import Rarity


def _make_entity(name: str, rarity: Rarity = Rarity.COMMON) -> ResolvedEntity:
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
        on_fish=None,
        contents_visible=False,
        rarity=rarity,
    )


def _make_instance(
    name: str, rarity: Rarity = Rarity.COMMON, instance_id: UUID | None = None
) -> EntityInstance:
    return EntityInstance(
        instance_id=instance_id or uuid4(),
        entity=_make_entity(name, rarity),
        room_id="test-room",
        owner_id=None,
        _pool=cast(asyncpg.Pool, None),
    )


def _make_room(room_id: str = "test-room", name: str = "Test Room") -> Room:
    return Room(
        id=room_id,
        name=name,
        description="A test room.",
        zone_id="test-zone",
        _pool=None,  # ty: ignore[invalid-argument-type]
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
        instance = _make_instance("Diamond", rarity=Rarity.RARE)
        choice = _make_choice(instance)
        assert "Diamond" in choice.name

    def test_no_rarity_entity_no_emoji(self):
        """Entities with 'none' rarity get no emoji suffix."""
        instance = _make_instance("Room Thing", rarity=Rarity.NONE)
        choice = _make_choice(instance)
        assert choice.name == "Room Thing"


class TestEntitiesToChoices:
    """Tests for entities_to_choices()."""

    def test_converts_list_of_entities(self):
        """Converts a list of entities to choices."""
        entities = [_make_instance("Sword"), _make_instance("Shield")]
        choices = entities_to_choices(entities)
        assert len(choices) == 2
        assert all(isinstance(c, app_commands.Choice) for c in choices)

    def test_truncates_at_max_choices(self):
        """Truncates to 25 choices (Discord limit)."""
        entities = [_make_instance(f"Item {i}") for i in range(30)]
        choices = entities_to_choices(entities)
        assert len(choices) == 25

    def test_empty_list(self):
        """Returns empty list for empty input."""
        assert entities_to_choices([]) == []


class TestEntityAutocompleteCacheGetters:
    """Tests for cache lookup methods."""

    def test_empty_cache_returns_none(self):
        """Empty cache returns None for any lookup."""
        cache = EntityAutocompleteCache()
        assert cache.get_room_choices("any-room") is None
        assert cache.get_focus_choices("any-room", uuid4()) is None
        assert cache.get_thread_choices(12345) is None

    def test_room_choices_hit(self):
        """Room choices are returned when present."""
        cache = EntityAutocompleteCache()
        choices = [app_commands.Choice(name="Test", value="test")]
        cache._room_choices["lobby"] = choices
        assert cache.get_room_choices("lobby") is choices

    def test_room_choices_miss(self):
        """Room choices return None for unknown room."""
        cache = EntityAutocompleteCache()
        cache._room_choices["lobby"] = []
        assert cache.get_room_choices("other-room") is None

    def test_focus_choices_hit(self):
        """Focus choices are returned for matching (room, instance) pair."""
        cache = EntityAutocompleteCache()
        uid = uuid4()
        choices = [app_commands.Choice(name="Item", value="entity://abc")]
        cache._focus_choices[("lobby", str(uid))] = choices
        assert cache.get_focus_choices("lobby", uid) is choices

    def test_focus_choices_miss_wrong_room(self):
        """Focus choices return None when room doesn't match."""
        cache = EntityAutocompleteCache()
        uid = uuid4()
        cache._focus_choices[("lobby", str(uid))] = []
        assert cache.get_focus_choices("other-room", uid) is None

    def test_focus_choices_miss_wrong_instance(self):
        """Focus choices return None when instance doesn't match."""
        cache = EntityAutocompleteCache()
        cache._focus_choices[("lobby", str(uuid4()))] = []
        assert cache.get_focus_choices("lobby", uuid4()) is None


class TestInvalidateRoom:
    """Tests for EntityAutocompleteCache.invalidate_room()."""

    def test_invalidate_removes_room_choices(self):
        """Room choices are removed after invalidation."""
        cache = EntityAutocompleteCache()
        cache._room_choices["lobby"] = [app_commands.Choice(name="X", value="x")]
        cache.invalidate_room("lobby")
        assert cache.get_room_choices("lobby") is None

    def test_invalidate_removes_focus_choices_for_room(self):
        """All focus choices for the room are removed."""
        cache = EntityAutocompleteCache()
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
        cache = EntityAutocompleteCache()
        cache.invalidate_room("nonexistent")  # Should not raise


class TestCreateInvalidatorFactory:
    """Tests for EntityAutocompleteCache.create_invalidator()."""

    def test_returns_cache_invalidation_observer(self):
        """create_invalidator returns a CacheInvalidationObserver."""
        cache = EntityAutocompleteCache()
        result = cache.create_invalidator(None, "room")  # ty: ignore[invalid-argument-type]
        assert isinstance(result, CacheInvalidationObserver)

    def test_invalidator_invalidates_cache_on_notify(self):
        """The returned observer invalidates cache entries on notify()."""
        cache = EntityAutocompleteCache()
        cache._room_choices["lobby"] = [app_commands.Choice(name="X", value="x")]
        cache._room_choices["garden"] = [app_commands.Choice(name="Y", value="y")]

        invalidator = cache.create_invalidator(None, "lobby")  # ty: ignore[invalid-argument-type]
        entity = _make_instance("Sword")
        picked_up = replace(entity, room_id=None, owner_id=12345)
        invalidator.notify(EntityPickedUpEvent(instance=picked_up))

        assert cache.get_room_choices("lobby") is None
        assert cache.get_room_choices("garden") is not None


class TestThreadChoices:
    """Tests for thread cache tier."""

    def test_thread_choices_hit(self):
        """Thread choices are returned when present."""
        cache = EntityAutocompleteCache()
        choices = [app_commands.Choice(name="Sword ⚪", value="entity://abc")]
        cache._thread_choices[99999] = choices
        assert cache.get_thread_choices(99999) is choices

    def test_thread_choices_miss(self):
        """Thread choices return None for unknown thread."""
        cache = EntityAutocompleteCache()
        cache._thread_choices[99999] = []
        assert cache.get_thread_choices(11111) is None

    def test_invalidate_thread_removes_entry(self):
        """invalidate_thread removes the cached entry."""
        cache = EntityAutocompleteCache()
        cache._thread_choices[99999] = [app_commands.Choice(name="X", value="x")]
        cache.invalidate_thread(99999)
        assert cache.get_thread_choices(99999) is None

    def test_invalidate_thread_unknown_is_noop(self):
        """Invalidating an unknown thread doesn't raise."""
        cache = EntityAutocompleteCache()
        cache.invalidate_thread(99999)  # Should not raise

    def test_invalidate_thread_does_not_affect_other_threads(self):
        """Invalidating one thread leaves other threads intact."""
        cache = EntityAutocompleteCache()
        choices_a = [app_commands.Choice(name="A", value="a")]
        choices_b = [app_commands.Choice(name="B", value="b")]
        cache._thread_choices[111] = choices_a
        cache._thread_choices[222] = choices_b

        cache.invalidate_thread(111)

        assert cache.get_thread_choices(111) is None
        assert cache.get_thread_choices(222) is choices_b
