"""Unit tests for the skill registry."""

from __future__ import annotations

from mudd.skills.registry import SKILL_COUNT, Skill


class TestSkill:
    def test_has_five_skills(self) -> None:
        assert len(Skill) == 5

    def test_skill_count_matches(self) -> None:
        assert len(Skill) == SKILL_COUNT

    def test_members(self) -> None:
        assert Skill.AGILITY == "agility"
        assert Skill.ATTACK == "attack"
        assert Skill.SPEECH == "speech"
        assert Skill.VITALITY == "vitality"
        assert Skill.FISHING == "fishing"

    def test_display_names(self) -> None:
        assert Skill.AGILITY.display_name == "Agility"
        assert Skill.ATTACK.display_name == "Attack"
        assert Skill.SPEECH.display_name == "Speech"
        assert Skill.VITALITY.display_name == "Vitality"
        assert Skill.FISHING.display_name == "Fishing"

    def test_is_str_enum(self) -> None:
        # StrEnum values can be used as strings directly
        assert isinstance(Skill.AGILITY, str)
        assert f"Skill: {Skill.AGILITY}" == "Skill: agility"

    def test_iteration(self) -> None:
        skills = list(Skill)
        assert len(skills) == SKILL_COUNT
        assert Skill.AGILITY in skills

    def test_emoji(self) -> None:
        assert Skill.AGILITY.emoji == "⚡"
        assert Skill.ATTACK.emoji == "⚔️"
        assert Skill.SPEECH.emoji == "💬"
        assert Skill.VITALITY.emoji == "❤️"
        assert Skill.FISHING.emoji == "🎣"

    def test_all_skills_have_emoji(self) -> None:
        for skill in Skill:
            assert isinstance(skill.emoji, str)
            assert len(skill.emoji) > 0
