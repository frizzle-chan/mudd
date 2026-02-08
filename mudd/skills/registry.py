"""Skill registry for the skills system."""

from __future__ import annotations

from enum import StrEnum


class Skill(StrEnum):
    """Available skills in the game."""

    AGILITY = "agility"
    ATTACK = "attack"
    SPEECH = "speech"
    VITALITY = "vitality"
    FISHING = "fishing"

    @property
    def display_name(self) -> str:
        """Human-readable display name for this skill."""
        return self.value.capitalize()


SKILL_COUNT: int = len(Skill)
