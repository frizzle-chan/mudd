"""Unit tests for SkillsObserver event routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mudd.events.types import (
    BroadcastEvent,
    EntityDestroyedEvent,
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


def _make_observer(
    *,
    reconciler: object | None = None,
) -> SkillsObserver:
    """Create a SkillsObserver with a fake pool."""
    return SkillsObserver(
        _pool=None,  # type: ignore[arg-type]
        _user_id=123,
        _room_id="foyer",
        _reconciler=reconciler,  # type: ignore[arg-type]
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

    def test_unrelated_event_ignored(self) -> None:
        obs = _make_observer()
        obs.notify(BroadcastEvent(message="hello"))
        assert obs._queued_grants == []


class TestGrantXPSignal:
    def test_grant_xp_signal_adds_to_grants(self) -> None:
        obs = _make_observer()
        obs.notify(GrantXPSignal(skill="vitality", amount=100))
        assert obs._queued_grants == [("vitality", 100)]

    def test_multiple_signals(self) -> None:
        obs = _make_observer()
        obs.notify(GrantXPSignal(skill="vitality", amount=100))
        obs.notify(GrantXPSignal(skill="speech", amount=50))
        assert len(obs._queued_grants) == 2


class TestEntityDestroyedNotQueued:
    def test_entity_destroyed_does_not_queue_attack_xp(
        self,
    ) -> None:
        """EntityDestroyedEvent is not handled by SkillsObserver.

        Attack XP should be handled by the cog/scene, not
        implicitly, because destruction can come from non-attack
        sources (e.g., food consumption).
        """
        obs = _make_observer()
        # EntityDestroyedEvent requires an EntityInstance;
        # since we're testing notify routing, we use a mock
        from unittest.mock import MagicMock

        fake_instance = MagicMock()
        obs.notify(EntityDestroyedEvent(instance=fake_instance))
        assert obs._queued_grants == []


# -- XPResult fixtures for event tests --

_NO_LEVELUP = XPResult(skill="agility", old_level=1, new_level=1, old_xp=0, new_xp=28)
_LEVELUP = XPResult(skill="vitality", old_level=1, new_level=2, old_xp=0, new_xp=100)


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
        assert event.skill == "vitality"
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
        assert events[0].skill == "vitality"

    def test_includes_room_id(self) -> None:
        obs = _make_observer()
        obs._results = [_LEVELUP]
        assert obs.get_level_up_events()[0].room_id == "foyer"

    def test_empty_when_no_levelups(self) -> None:
        obs = _make_observer()
        obs._results = [_NO_LEVELUP]
        assert obs.get_level_up_events() == []


class TestFlush:
    @pytest.mark.asyncio
    async def test_exception_does_not_block_later_grants(self) -> None:
        """A failed grant_xp call should not prevent subsequent grants."""
        obs = _make_observer()
        obs.notify(GrantXPSignal(skill="agility", amount=28))
        obs.notify(GrantXPSignal(skill="vitality", amount=100))

        call_count = 0

        async def mock_grant_xp(
            pool: object, user_id: int, skill: str, amount: int
        ) -> XPResult:
            nonlocal call_count
            call_count += 1
            if skill == "agility":
                raise RuntimeError("db down")
            return _LEVELUP

        with patch(
            "mudd.observers.skills.UserSkill.grant_xp",
            side_effect=mock_grant_xp,
        ):
            await obs.flush()

        assert call_count == 2
        # Only the second grant succeeded
        assert len(obs._results) == 1
        assert obs._results[0].skill == "vitality"
        # Queue was cleared
        assert obs._queued_grants == []

    @pytest.mark.asyncio
    async def test_reconciler_receives_events(self) -> None:
        """After flush, reconciler.notify() gets XP and level-up events."""
        mock_reconciler = MagicMock()
        mock_reconciler.notify = MagicMock()  # sync method
        mock_reconciler.flush = AsyncMock()  # async method
        obs = _make_observer(reconciler=mock_reconciler)
        obs.notify(GrantXPSignal(skill="vitality", amount=100))

        with patch(
            "mudd.observers.skills.UserSkill.grant_xp",
            return_value=_LEVELUP,
        ):
            await obs.flush()

        # Should have been called with an XPGainedEvent and a LevelUpEvent
        calls = [c.args[0] for c in mock_reconciler.notify.call_args_list]
        assert any(isinstance(e, XPGainedEvent) for e in calls)
        assert any(isinstance(e, LevelUpEvent) for e in calls)
        mock_reconciler.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reconciler_not_called_when_none(self) -> None:
        """Flush works when no reconciler is set."""
        obs = _make_observer()
        obs.notify(GrantXPSignal(skill="agility", amount=28))

        with patch(
            "mudd.observers.skills.UserSkill.grant_xp",
            return_value=_NO_LEVELUP,
        ):
            await obs.flush()

        assert len(obs._results) == 1
