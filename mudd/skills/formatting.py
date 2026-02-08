"""Formatting utilities for skills display."""

from __future__ import annotations

import re

from mudd.models.skills import UserSkill
from mudd.skills.registry import SKILL_COUNT, Skill
from mudd.skills.xp import MAX_LEVEL, xp_for_level

# Progress bar characters
BAR_FILLED = "\u2501"  # ━
BAR_EMPTY = "\u2591"  # ░
BAR_LENGTH = 20

# Milestone role names and thresholds
MILESTONE_ROLES: list[tuple[str, int]] = [
    ("Newbie", SKILL_COUNT * 1),
    ("Apprentice", SKILL_COUNT * 3),
    ("Adventurer", SKILL_COUNT * 10),
    ("Journeyman", SKILL_COUNT * 20),
    ("Expert", SKILL_COUNT * 40),
    ("Veteran", SKILL_COUNT * 60),
    ("Hero", SKILL_COUNT * 80),
    ("Legend", SKILL_COUNT * 99),
]

MILESTONE_ROLE_NAMES: list[str] = [name for name, _ in MILESTONE_ROLES]

# Nickname format
MAX_NICK_LENGTH = 32
NICK_SUFFIX_TEMPLATE = " (LV{})"
_LEVEL_SUFFIX_RE = re.compile(r"\s*\(LV\d+\)$")


def format_progress_bar(current_xp: int, level: int) -> str:
    """Format a progress bar for XP toward the next level.

    Args:
        current_xp: Current cumulative XP
        level: Current level

    Returns:
        Formatted string like "━━━━━━━━━━░░░░░░░░░░ 340/547 XP"
    """
    if level >= MAX_LEVEL:
        return BAR_FILLED * BAR_LENGTH + " MAX"

    current_level_xp = xp_for_level(level)
    next_level_xp = xp_for_level(level + 1)
    xp_in_level = current_xp - current_level_xp
    xp_needed = next_level_xp - current_level_xp

    ratio = 1.0 if xp_needed <= 0 else xp_in_level / xp_needed

    filled = int(ratio * BAR_LENGTH)
    empty = BAR_LENGTH - filled

    bar = BAR_FILLED * filled + BAR_EMPTY * empty
    return f"{bar} {xp_in_level}/{xp_needed} XP"


type SkillData = list[tuple[str, int, int]]


def _extract_skill_data(skills: list[UserSkill]) -> SkillData:
    """Extract ordered (display_name, level, xp) tuples from skill list."""
    skill_map = {s.skill: s for s in skills}
    result: SkillData = []
    for skill_enum in Skill:
        user_skill = skill_map.get(str(skill_enum))
        if user_skill is None:
            level = 1
            xp = 0
        else:
            level = user_skill.level
            xp = user_skill.xp
        result.append((skill_enum.display_name, level, xp))
    return result


def _xp_parts(xp: int, level: int) -> tuple[int, int]:
    """Return (xp_in_level, xp_needed) for progress display."""
    if level >= MAX_LEVEL:
        return (0, 0)
    current_level_xp = xp_for_level(level)
    next_level_xp = xp_for_level(level + 1)
    return (xp - current_level_xp, next_level_xp - current_level_xp)


def _bar_string(xp: int, level: int) -> str:
    """Return just the bar characters (no XP text)."""
    if level >= MAX_LEVEL:
        return BAR_FILLED * BAR_LENGTH

    xp_in_level, xp_needed = _xp_parts(xp, level)
    ratio = 1.0 if xp_needed <= 0 else xp_in_level / xp_needed
    filled = int(ratio * BAR_LENGTH)
    empty = BAR_LENGTH - filled
    return BAR_FILLED * filled + BAR_EMPTY * empty


def _format_option_a(data: SkillData) -> list[str]:
    """Option A: Code block, monospaced alignment."""
    max_name = max(len(name) for name, _, _ in data)
    # Compute max XP string width for consistent padding
    xp_strings: list[str] = []
    for _, level, xp in data:
        if level >= MAX_LEVEL:
            xp_strings.append("MAX")
        else:
            xp_in, xp_need = _xp_parts(xp, level)
            xp_strings.append(f"{xp_in}/{xp_need} XP")
    max_xp_width = max(len(s) for s in xp_strings)

    lines = ["```"]
    for i, (name, level, xp) in enumerate(data):
        padded_name = name.ljust(max_name)
        padded_level = str(level).rjust(2)
        bar = _bar_string(xp, level)
        padded_xp = xp_strings[i].rjust(max_xp_width)
        lines.append(f"{padded_name}  Lv.{padded_level}  {bar}  {padded_xp}")
    lines.append("```")
    return lines


def _format_option_b(data: SkillData) -> list[str]:
    """Option B: Two-line layout, spaced (blank line between skills)."""
    lines: list[str] = []
    for i, (name, level, xp) in enumerate(data):
        bar = _bar_string(xp, level)
        if level >= MAX_LEVEL:
            xp_str = "MAX"
        else:
            xp_in, xp_need = _xp_parts(xp, level)
            xp_str = f"{xp_in}/{xp_need} XP"
        lines.append(f"**{name}** \u2014 Lv. {level}")
        lines.append(f"{bar} {xp_str}")
        if i < len(data) - 1:
            lines.append("")
    return lines


def _format_option_c(data: SkillData) -> list[str]:
    """Option C: Two-line layout, compact (no blank line between skills)."""
    lines: list[str] = []
    for name, level, xp in data:
        bar = _bar_string(xp, level)
        if level >= MAX_LEVEL:
            xp_str = "MAX"
        else:
            xp_in, xp_need = _xp_parts(xp, level)
            xp_str = f"{xp_in}/{xp_need} XP"
        lines.append(f"**{name}** \u2014 Lv. {level}")
        lines.append(f"{bar} {xp_str}")
    return lines


def _format_option_d(data: SkillData) -> list[str]:
    """Option D: Single-line with inline code XP."""
    # Compute max XP string width for consistent backtick padding
    xp_strings: list[str] = []
    for _, level, xp in data:
        if level >= MAX_LEVEL:
            xp_strings.append("MAX")
        else:
            xp_in, xp_need = _xp_parts(xp, level)
            xp_strings.append(f"{xp_in}/{xp_need} XP")
    max_xp_width = max(len(s) for s in xp_strings)

    lines: list[str] = []
    for i, (name, level, xp) in enumerate(data):
        bar = _bar_string(xp, level)
        padded_xp = xp_strings[i].rjust(max_xp_width)
        lines.append(f"**{name}** Lv. {level} {bar} `{padded_xp}`")
    return lines


def format_skills_message(skills: list[UserSkill], total_level: int) -> str:
    """Format the full skills overview message with all layout options.

    Renders four layout options (A-D) for visual comparison in Discord.

    Args:
        skills: List of UserSkill instances
        total_level: Sum of all skill levels

    Returns:
        Formatted Discord message string
    """
    data = _extract_skill_data(skills)

    sections = [f"**Total Level: {total_level}**", ""]

    options: list[tuple[str, list[str]]] = [
        ("Option A: Code Block", _format_option_a(data)),
        ("Option B: Two-Line Spaced", _format_option_b(data)),
        ("Option C: Two-Line Compact", _format_option_c(data)),
        ("Option D: Inline Code XP", _format_option_d(data)),
    ]

    for label, lines in options:
        sections.append(f"**\u2014 {label} \u2014**")
        sections.extend(lines)
        sections.append("")

    return "\n".join(sections)


def format_nickname(display_name: str, total_level: int) -> str:
    """Format a Discord nickname with total level suffix.

    Truncates display_name if the result would exceed 32 chars.

    Args:
        display_name: User's display name
        total_level: Sum of all skill levels

    Returns:
        Formatted nickname string
    """
    display_name = _LEVEL_SUFFIX_RE.sub("", display_name)
    suffix = NICK_SUFFIX_TEMPLATE.format(total_level)
    max_name_len = MAX_NICK_LENGTH - len(suffix)

    if len(display_name) > max_name_len:
        display_name = display_name[:max_name_len]

    return f"{display_name}{suffix}"


def get_milestone_role(total_level: int) -> str | None:
    """Get the milestone role name for a total level.

    Returns the highest milestone role the player qualifies for.

    Args:
        total_level: Sum of all skill levels

    Returns:
        Role name or None if below minimum threshold
    """
    result = None
    for name, threshold in MILESTONE_ROLES:
        if total_level >= threshold:
            result = name
    return result


def format_level_up_message(
    display_name: str,
    skill: str,
    new_level: int,
) -> str:
    """Format a level-up announcement message.

    Args:
        display_name: User's display name
        skill: Skill name
        new_level: New level achieved

    Returns:
        Formatted announcement string
    """
    # Get display name from Skill enum if possible
    try:
        skill_display = Skill(skill).display_name
    except ValueError:
        skill_display = skill.capitalize()

    return f"**{display_name}** advanced **{skill_display}** to level {new_level}!"
