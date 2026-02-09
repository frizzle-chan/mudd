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

    @property
    def emoji(self) -> str:
        """Emoji icon for this skill."""
        match self:
            case Skill.AGILITY:
                return "\u26a1"
            case Skill.ATTACK:
                return "\u2694\ufe0f"
            case Skill.SPEECH:
                return "\U0001f4ac"
            case Skill.VITALITY:
                return "\u2764\ufe0f"
            case Skill.FISHING:
                return "\U0001f3a3"


SKILL_COUNT: int = len(Skill)
