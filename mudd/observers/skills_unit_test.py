"""Unit tests for SkillsObserver event routing."""

from __future__ import annotations

from mudd.events.types import (
    BroadcastEvent,
    GrantXPSignal,
    LevelUpEvent,
    UserMovedEvent,
    XPGainedEvent,
)
from mudd.models.skills import XPResult
from mudd.observers.skills import (
    AGILITY_XP_PER_MOVE,
    SkillsObserver,
)
from mudd.skills.registry import Skill


def _make_observer() -> SkillsObserver:
    """Create a SkillsObserver with a fake pool."""
    return SkillsObserver(
        _pool=None,  # type: ignore[arg-type]
        _user_id=123,
        _room_id="foyer",
    )


class TestNotify:
    def test_user_moved_queues_agility_xp(self) -> None:
        obs = _make_observer()
        event = UserMovedEvent(
            user_id=123,
            from_room="foyer",
            to_room="hallway",
            guild_id=1,
        )
        obs.notify(event)
        assert obs._queued_grants == [(Skill.AGILITY, AGILITY_XP_PER_MOVE)]

    def test_other_user_moved_ignored(self) -> None:
        obs = _make_observer()
        event = UserMovedEvent(
            user_id=999,
            from_room="foyer",
            to_room="hallway",
            guild_id=1,
        )
        obs.notify(event)
        assert obs._queued_grants == []

    def test_user_moved_updates_room_id(self) -> None:
        obs = _make_observer()
        assert obs._room_id == "foyer"
        event = UserMovedEvent(
            user_id=123,
            from_room="foyer",
            to_room="hallway",
            guild_id=1,
        )
        obs.notify(event)
        assert obs._room_id == "hallway"

    def test_unrelated_event_ignored(self) -> None:
        obs = _make_observer()
        obs.notify(BroadcastEvent(message="hello"))
        assert obs._queued_grants == []


class TestGrantXPSignal:
    def test_grant_xp_signal_adds_to_grants(self) -> None:
        obs = _make_observer()
        obs.notify(GrantXPSignal(skill=Skill.VITALITY, amount=100))
        assert obs._queued_grants == [(Skill.VITALITY, 100)]

    def test_multiple_signals(self) -> None:
        obs = _make_observer()
        obs.notify(GrantXPSignal(skill=Skill.VITALITY, amount=100))
        obs.notify(GrantXPSignal(skill=Skill.SPEECH, amount=50))
        assert len(obs._queued_grants) == 2


# -- XPResult fixtures for event tests --

_NO_LEVELUP = XPResult(
    skill=Skill.AGILITY, old_level=1, new_level=1, old_xp=0, new_xp=28
)
_LEVELUP = XPResult(
    skill=Skill.VITALITY, old_level=1, new_level=2, old_xp=0, new_xp=100
)


class TestGetXPEvents:
    def test_includes_all_results(self) -> None:
        obs = _make_observer()
        obs._results = [_NO_LEVELUP, _LEVELUP]
        events = obs.get_xp_events()
        assert len(events) == 2
        assert all(isinstance(e, XPGainedEvent) for e in events)

    def test_maps_fields_correctly(self) -> None:
        obs = _make_observer()
        obs._results = [_LEVELUP]
        event = obs.get_xp_events()[0]
        assert event.user_id == 123
        assert event.skill == Skill.VITALITY
        assert event.old_level == 1
        assert event.new_level == 2
        assert event.old_xp == 0
        assert event.new_xp == 100

    def test_empty_results(self) -> None:
        obs = _make_observer()
        assert obs.get_xp_events() == []


class TestGetLevelUpEvents:
    def test_filters_non_levelups(self) -> None:
        obs = _make_observer()
        obs._results = [_NO_LEVELUP, _LEVELUP]
        events = obs.get_level_up_events()
        assert len(events) == 1
        assert isinstance(events[0], LevelUpEvent)
        assert events[0].skill == Skill.VITALITY

    def test_includes_room_id(self) -> None:
        obs = _make_observer()
        obs.notify(
            UserMovedEvent(
                user_id=123,
                from_room="foyer",
                to_room="hallway",
                guild_id=1,
            )
        )
        obs._results = [_LEVELUP]
        assert obs.get_level_up_events()[0].room_id == "hallway"

    def test_empty_when_no_levelups(self) -> None:
        obs = _make_observer()
        obs._results = [_NO_LEVELUP]
        assert obs.get_level_up_events() == []
