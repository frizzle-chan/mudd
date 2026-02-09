"""Unit tests for ViewSkill."""

from __future__ import annotations

from mudd.skills.registry import Skill
from mudd.views import ViewSkill


class TestViewSkill:
    def test_name_bold_with_emoji(self) -> None:
        view = ViewSkill(Skill.AGILITY)
        assert view.name == "**⚡ Agility**"

    def test_display_name_emoji_no_bold(self) -> None:
        view = ViewSkill(Skill.AGILITY)
        assert view.display_name == "⚡ Agility"

    def test_str_returns_name(self) -> None:
        view = ViewSkill(Skill.AGILITY)
        assert str(view) == view.name

    def test_all_skills_have_emoji(self) -> None:
        for skill in Skill:
            view = ViewSkill(skill)
            assert view.display_name != skill.display_name

    def test_attack_emoji(self) -> None:
        assert ViewSkill(Skill.ATTACK).name == "**⚔️ Attack**"

    def test_speech_emoji(self) -> None:
        assert ViewSkill(Skill.SPEECH).name == "**💬 Speech**"

    def test_vitality_emoji(self) -> None:
        assert ViewSkill(Skill.VITALITY).name == "**❤️ Vitality**"

    def test_fishing_emoji(self) -> None:
        assert ViewSkill(Skill.FISHING).name == "**🎣 Fishing**"
