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


SKILL_EMOJI: dict[Skill, str] = {
    Skill.AGILITY: "\U0001f3c3",
    Skill.ATTACK: "\u2694\ufe0f",
    Skill.SPEECH: "\U0001f4ac",
    Skill.VITALITY: "\u2764\ufe0f",
    Skill.FISHING: "\U0001f3a3",
}

SKILL_COUNT: int = len(Skill)
