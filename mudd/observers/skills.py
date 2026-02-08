"""SkillsObserver awards implicit XP and processes XP results."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import asyncpg

from mudd.events.types import (
    GameEvent,
    GrantXPSignal,
    LevelUpEvent,
    UserMovedEvent,
    XPGainedEvent,
)
from mudd.models.skills import UserSkill, XPResult
from mudd.skills.registry import Skill

logger = logging.getLogger(__name__)

# Implicit XP amounts
AGILITY_XP_PER_MOVE: int = 28


@dataclass
class SkillsObserver:
    """Observer that awards implicit XP from game events.

    Listens for game events and queues XP grants:
    - UserMovedEvent -> Agility XP (implicit)
    - GrantXPSignal -> explicit XP from template effects

    During flush(), processes all queued grants via UserSkill.grant_xp()
    and stores results. Event forwarding to DiscordReconciler is handled
    externally by flush_all().
    """

    _pool: asyncpg.Pool
    _user_id: int
    _room_id: str
    _queued_grants: list[tuple[Skill, int, str]] = field(default_factory=list)
    _results: list[tuple[XPResult, str]] = field(default_factory=list)

    def notify(self, event: GameEvent) -> None:
        """Receive an event and queue XP grants.

        Args:
            event: The game event to process
        """
        match event:
            case UserMovedEvent(user_id=uid, to_room=to_room) if uid == self._user_id:
                self._queued_grants.append(
                    (Skill.AGILITY, AGILITY_XP_PER_MOVE, to_room)
                )
            case GrantXPSignal(skill=skill, amount=amount):
                self._queued_grants.append((skill, amount, self._room_id))

    async def flush(self) -> None:
        """Process all queued XP grants.

        Calls UserSkill.grant_xp() for each queued grant and
        collects the results. Event forwarding to DiscordReconciler
        is handled externally by flush_all().
        """
        for skill, amount, room_id in self._queued_grants:
            try:
                result = await UserSkill.grant_xp(
                    self._pool, self._user_id, skill, amount
                )
                self._results.append((result, room_id))
            except Exception:
                logger.exception(
                    "Failed to grant %d %s XP to user %d",
                    amount,
                    skill,
                    self._user_id,
                )
        self._queued_grants.clear()

    @property
    def results(self) -> list[XPResult]:
        """XP grant results from the last flush."""
        return [r for r, _ in self._results]

    @property
    def level_ups(self) -> list[XPResult]:
        """Results where the user leveled up."""
        return [r for r, _ in self._results if r.leveled_up]

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
            for r, _room_id in self._results
        ]

    def get_level_up_events(self) -> list[LevelUpEvent]:
        """Build LevelUpEvent for each level-up result."""
        return [
            LevelUpEvent(
                user_id=self._user_id,
                skill=r.skill,
                new_level=r.new_level,
                room_id=room_id,
            )
            for r, room_id in self._results
            if r.leveled_up
        ]
