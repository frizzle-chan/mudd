"""Unit tests for skills formatting utilities."""

from __future__ import annotations

from typing import ClassVar

from mudd.models.skills import UserSkill
from mudd.skills.formatting import (
    MILESTONE_ROLE_NAMES,
    format_level_up_message,
    format_nickname,
    format_progress_bar,
    format_skills_message,
    get_milestone_role,
)
from mudd.skills.registry import SKILL_COUNT, Skill
from mudd.skills.xp import MAX_LEVEL
from mudd.utils.progress_bar import SHADED


class TestFormatProgressBar:
    def test_zero_xp_level_1(self) -> None:
        bar = format_progress_bar(0, 1)
        assert "░" in bar
        assert "0/83 XP" in bar
        # Bar wrapped in backticks
        assert "`" in bar

    def test_max_level_shows_max(self) -> None:
        bar = format_progress_bar(13_034_431, MAX_LEVEL)
        assert "MAX" in bar
        assert "█" in bar

    def test_partial_progress(self) -> None:
        # Level 1 needs 83 XP to get to level 2
        bar = format_progress_bar(41, 1)
        # Should contain some filled and some empty shading
        assert any(c in bar for c in SHADED[1:])  # at least one non-empty shade
        assert "░" in bar  # some empty portion
        assert "41/83 XP" in bar

    def test_bar_wrapped_in_backticks(self) -> None:
        bar = format_progress_bar(0, 1)
        # Bar portion should be wrapped in inline code
        assert bar.startswith("`")
        assert "`" in bar[1:]


class TestFormatSkillsMessage:
    _skills: ClassVar[list[UserSkill]] = [
        UserSkill(user_id=1, skill="agility", xp=0, level=1),
        UserSkill(user_id=1, skill="attack", xp=0, level=1),
        UserSkill(user_id=1, skill="speech", xp=0, level=1),
        UserSkill(user_id=1, skill="vitality", xp=0, level=1),
        UserSkill(user_id=1, skill="fishing", xp=0, level=1),
    ]

    def test_contains_heading(self) -> None:
        msg = format_skills_message(self._skills, 5, "Alice")
        assert msg.startswith("# Alice\n")

    def test_contains_all_skills(self) -> None:
        msg = format_skills_message(self._skills, 5, "Alice")
        assert "**⚡ Agility**" in msg
        assert "**⚔️ Attack**" in msg
        assert "**💬 Speech**" in msg
        assert "**❤️ Vitality**" in msg
        assert "**🎣 Fishing**" in msg

    def test_two_line_layout(self) -> None:
        msg = format_skills_message(self._skills, 5, "Alice")
        # Each skill uses "LV" prefix for level
        assert "LV1" in msg

    def test_skills_separated_by_blank_lines(self) -> None:
        msg = format_skills_message(self._skills, 5, "Alice")
        # Skills are separated by blank lines for readability
        lines = msg.split("\n")
        skill_blocks = [
            i for i, line in enumerate(lines) if "LV" in line and line.startswith("**")
        ]
        # Each skill block should have a blank line after its progress bar
        for idx in skill_blocks[:-1]:
            assert lines[idx + 2] == ""

    def test_progress_bars_in_inline_code(self) -> None:
        msg = format_skills_message(self._skills, 5, "Alice")
        # Each progress bar line should contain backtick-wrapped bar
        lines = msg.split("\n")
        bar_lines = [line for line in lines if "XP" in line]
        for line in bar_lines:
            assert "`" in line


class TestFormatSkillsMessageDeltas:
    _skills: ClassVar[list[UserSkill]] = [
        UserSkill(user_id=1, skill="agility", xp=0, level=1),
        UserSkill(user_id=1, skill="attack", xp=25, level=1),
        UserSkill(user_id=1, skill="speech", xp=0, level=1),
        UserSkill(user_id=1, skill="vitality", xp=0, level=1),
        UserSkill(user_id=1, skill="fishing", xp=0, level=1),
    ]

    def test_no_deltas_no_indicator(self) -> None:
        msg = format_skills_message(self._skills, 5, "Alice")
        assert "(+" not in msg

    def test_none_deltas_no_indicator(self) -> None:
        msg = format_skills_message(self._skills, 5, "Alice", deltas=None)
        assert "(+" not in msg

    def test_single_delta_shown(self) -> None:
        msg = format_skills_message(self._skills, 5, "Alice", deltas={Skill.ATTACK: 25})
        assert "(+25) \U0001f199" in msg

    def test_delta_only_on_matching_skill(self) -> None:
        msg = format_skills_message(self._skills, 5, "Alice", deltas={Skill.ATTACK: 25})
        lines = msg.split("\n")
        bar_lines = [line for line in lines if "XP" in line]
        # Only the Attack bar line should have the indicator
        lines_with_delta = [line for line in bar_lines if "(+25)" in line]
        assert len(lines_with_delta) == 1

    def test_multiple_deltas(self) -> None:
        msg = format_skills_message(
            self._skills,
            5,
            "Alice",
            deltas={Skill.ATTACK: 25, Skill.AGILITY: 10},
        )
        assert "(+25) \U0001f199" in msg
        assert "(+10) \U0001f199" in msg

    def test_zero_delta_not_shown(self) -> None:
        msg = format_skills_message(self._skills, 5, "Alice", deltas={Skill.ATTACK: 0})
        assert "(+" not in msg


class TestFormatNickname:
    def test_basic_format(self) -> None:
        assert format_nickname("Alice", 15) == "Alice (LV15)"

    def test_truncates_long_name(self) -> None:
        nick = format_nickname("A" * 30, 5)
        assert len(nick) <= 32

    def test_exact_32_chars(self) -> None:
        nick = format_nickname("A" * 26, 5)
        assert len(nick) <= 32

    def test_strips_existing_suffix(self) -> None:
        assert format_nickname("Player (LV5)", 6) == "Player (LV6)"

    def test_strips_suffix_long_name(self) -> None:
        long_name = "A" * 26 + " (LV5)"
        nick = format_nickname(long_name, 10)
        assert len(nick) <= 32
        assert nick.endswith("(LV10)")
        assert "(LV5)" not in nick

    def test_no_suffix_unchanged(self) -> None:
        assert format_nickname("Player", 5) == "Player (LV5)"


class TestGetMilestoneRole:
    def test_below_minimum_returns_none(self) -> None:
        assert get_milestone_role(0) is None

    def test_at_newbie_threshold(self) -> None:
        assert get_milestone_role(SKILL_COUNT * 1) == "Newbie"

    def test_at_legend_threshold(self) -> None:
        assert get_milestone_role(SKILL_COUNT * 99) == "Legend"

    def test_between_thresholds(self) -> None:
        # Between Apprentice (15) and Adventurer (50)
        role = get_milestone_role(SKILL_COUNT * 5)
        assert role == "Apprentice"

    def test_all_role_names_defined(self) -> None:
        assert len(MILESTONE_ROLE_NAMES) == 8


class TestFormatLevelUpMessage:
    def test_basic_format(self) -> None:
        msg = format_level_up_message("Alice", Skill.AGILITY, 5)
        assert "**Alice**" in msg
        assert "**⚡ Agility**" in msg
        assert "level 5" in msg

    def test_all_skills_format(self) -> None:
        for skill in Skill:
            msg = format_level_up_message("Bob", skill, 3)
            assert "**Bob**" in msg
            assert "level 3" in msg
