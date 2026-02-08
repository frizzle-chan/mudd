"""Unit tests for skills formatting utilities."""

from __future__ import annotations

from mudd.models.skills import UserSkill
from mudd.skills.formatting import (
    BAR_EMPTY,
    BAR_FILLED,
    BAR_LENGTH,
    MILESTONE_ROLE_NAMES,
    format_level_up_message,
    format_nickname,
    format_progress_bar,
    format_skills_message,
    get_milestone_role,
)
from mudd.skills.registry import SKILL_COUNT
from mudd.skills.xp import MAX_LEVEL


class TestFormatProgressBar:
    def test_zero_xp_level_1(self) -> None:
        bar = format_progress_bar(0, 1)
        assert BAR_EMPTY * BAR_LENGTH in bar
        assert "0/83 XP" in bar

    def test_max_level_shows_max(self) -> None:
        bar = format_progress_bar(13_034_431, MAX_LEVEL)
        assert "MAX" in bar
        assert BAR_FILLED * BAR_LENGTH in bar

    def test_partial_progress(self) -> None:
        # Level 1 needs 83 XP to get to level 2
        bar = format_progress_bar(41, 1)
        assert BAR_FILLED in bar
        assert BAR_EMPTY in bar
        assert "41/83 XP" in bar


class TestFormatSkillsMessage:
    _skills = [
        UserSkill(user_id=1, skill="agility", xp=0, level=1),
        UserSkill(user_id=1, skill="attack", xp=0, level=1),
        UserSkill(user_id=1, skill="speech", xp=0, level=1),
        UserSkill(user_id=1, skill="vitality", xp=0, level=1),
        UserSkill(user_id=1, skill="fishing", xp=0, level=1),
    ]

    def test_contains_total_level(self) -> None:
        msg = format_skills_message(self._skills, 5)
        assert "**Total Level: 5**" in msg

    def test_contains_all_skills(self) -> None:
        msg = format_skills_message(self._skills, 5)
        # Each skill name appears at least once across the options
        assert "Agility" in msg
        assert "Attack" in msg
        assert "Speech" in msg
        assert "Vitality" in msg
        assert "Fishing" in msg

    def test_contains_all_option_headers(self) -> None:
        msg = format_skills_message(self._skills, 5)
        assert "Option A" in msg
        assert "Option B" in msg
        assert "Option C" in msg
        assert "Option D" in msg

    def test_option_a_in_code_block(self) -> None:
        msg = format_skills_message(self._skills, 5)
        assert "```" in msg

    def test_option_b_has_separator_lines(self) -> None:
        msg = format_skills_message(self._skills, 5)
        # Option B uses em-dash separator between name and level
        assert "\u2014 Lv." in msg

    def test_option_c_compact_no_blank_lines(self) -> None:
        msg = format_skills_message(self._skills, 5)
        # Extract just the Option C skill lines (after header, before next header)
        start = msg.index("Option C")
        end = msg.index("Option D")
        section_c = msg[start:end]
        lines = section_c.split("\n")
        # The skill content lines (1 through 10) should have no blanks between them
        skill_lines = lines[1:11]  # 5 skills * 2 lines each
        assert all(line.strip() for line in skill_lines)

    def test_option_d_has_inline_code_xp(self) -> None:
        msg = format_skills_message(self._skills, 5)
        # Option D wraps XP in backticks
        start = msg.index("Option D")
        section_d = msg[start:]
        assert "`" in section_d
        assert "XP`" in section_d


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
        msg = format_level_up_message("Alice", "agility", 5)
        assert "**Alice**" in msg
        assert "**Agility**" in msg
        assert "level 5" in msg

    def test_unknown_skill_capitalized(self) -> None:
        msg = format_level_up_message("Bob", "unknown", 3)
        assert "Unknown" in msg
