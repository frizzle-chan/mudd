"""Unit tests for AutocompleteCache."""

from uuid import UUID, uuid4

from discord import app_commands

from mudd.cogs.autocomplete_cache import AutocompleteCache, _make_choice
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
