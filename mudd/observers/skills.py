"""SkillsObserver awards implicit XP and processes XP results."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import asyncpg

from mudd.events.types import (
    GameEvent,
    LevelUpEvent,
    UserMovedEvent,
    XPGainedEvent,
)
from mudd.models.skills import UserSkill, XPResult
from mudd.skills.registry import Skill

if TYPE_CHECKING:
    from mudd.events.observer import Observer

logger = logging.getLogger(__name__)

# Implicit XP amounts
AGILITY_XP_PER_MOVE: int = 28


@dataclass
class SkillsObserver:
    """Observer that awards implicit XP from game events.

    Listens for game events and queues implicit XP grants:
    - UserMovedEvent -> Agility XP

    Also accepts explicit XP grants via queue_xp() (from template effects).
    During flush(), processes all queued grants via UserSkill.grant_xp()
    and emits XPGainedEvent/LevelUpEvent to downstream observers.
    """

    _pool: asyncpg.Pool
    _user_id: int
    _room_id: str
    _downstream: tuple[Observer, ...] = ()
    _queued_grants: list[tuple[str, int]] = field(default_factory=list)
    _results: list[XPResult] = field(default_factory=list)

    def notify(self, event: GameEvent) -> None:
        """Receive an event and queue implicit XP grants.

        Args:
            event: The game event to process
        """
        match event:
            case UserMovedEvent(user_id=uid) if uid == self._user_id:
                self._queued_grants.append((Skill.AGILITY, AGILITY_XP_PER_MOVE))

    def queue_xp(self, skill: str, amount: int) -> None:
        """Queue an XP grant for processing during flush.

        Args:
            skill: Skill name to grant XP in
            amount: Amount of XP to grant
        """
        self._queued_grants.append((skill, amount))

    async def flush(self) -> None:
        """Process all queued XP grants.

        Calls UserSkill.grant_xp() for each queued grant,
        collects the results, and emits XPGainedEvent/LevelUpEvent
        to downstream observers (e.g., SkillsReconciler).
        """
        for skill, amount in self._queued_grants:
            try:
                result = await UserSkill.grant_xp(
                    self._pool, self._user_id, skill, amount
                )
                self._results.append(result)
            except Exception:
                logger.exception(
                    "Failed to grant %d %s XP to user %d",
                    amount,
                    skill,
                    self._user_id,
                )
        self._queued_grants.clear()

        # Emit events to downstream observers
        for event in self.get_xp_events():
            for obs in self._downstream:
                obs.notify(event)
        for event in self.get_level_up_events():
            for obs in self._downstream:
                obs.notify(event)

    @property
    def results(self) -> list[XPResult]:
        """XP grant results from the last flush."""
        return self._results

    @property
    def level_ups(self) -> list[XPResult]:
        """Results where the user leveled up."""
        return [r for r in self._results if r.leveled_up]

    def get_xp_events(self) -> list[XPGainedEvent]:
        """Build XPGainedEvent for each result."""
        return [
            XPGainedEvent(
                user_id=self._user_id,
                skill=r.skill,
                old_level=r.old_level,
                new_level=r.new_level,
                old_xp=r.old_xp,
                new_xp=r.new_xp,
            )
            for r in self._results
        ]

    def get_level_up_events(self) -> list[LevelUpEvent]:
        """Build LevelUpEvent for each level-up result."""
        return [
            LevelUpEvent(
                user_id=self._user_id,
                skill=r.skill,
                new_level=r.new_level,
                room_id=self._room_id,
            )
            for r in self._results
            if r.leveled_up
        ]
