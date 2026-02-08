"""Unit tests for SkillsObserver event routing."""

from __future__ import annotations

from mudd.events.types import (
    BroadcastEvent,
    EntityDestroyedEvent,
    UserMovedEvent,
)
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

    def test_unrelated_event_ignored(self) -> None:
        obs = _make_observer()
        obs.notify(BroadcastEvent(message="hello"))
        assert obs._queued_grants == []


class TestQueueXP:
    def test_queue_xp_adds_to_grants(self) -> None:
        obs = _make_observer()
        obs.queue_xp("vitality", 100)
        assert obs._queued_grants == [("vitality", 100)]

    def test_queue_multiple(self) -> None:
        obs = _make_observer()
        obs.queue_xp("vitality", 100)
        obs.queue_xp("speech", 50)
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
