"""Formatting utilities for skills display."""

from __future__ import annotations

import re

from mudd.models.skills import UserSkill
from mudd.skills.registry import SKILL_COUNT, Skill
from mudd.skills.xp import MAX_LEVEL, xp_for_level
from mudd.utils.progress_bar import DEFAULT_SIZE, shaded_bar
from mudd.views import ViewSkill

# Milestone role names and thresholds
MILESTONE_ROLES: list[tuple[str, int]] = [
    ("Newbie", SKILL_COUNT * 1),
    ("Apprentice", SKILL_COUNT * 3),
    ("Adventurer", SKILL_COUNT * 10),
    ("Adept", SKILL_COUNT * 20),
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
    """Format a shaded progress bar for XP toward the next level.

    Args:
        current_xp: Current cumulative XP
        level: Current level

    Returns:
        Formatted string like "``░░░░░░░░░░░░░░░░░░░░`` 0/83 XP"
    """
    if level >= MAX_LEVEL:
        bar = shaded_bar(100, DEFAULT_SIZE)
        return f"`{bar}` MAX"

    current_level_xp = xp_for_level(level)
    next_level_xp = xp_for_level(level + 1)
    xp_in_level = current_xp - current_level_xp
    xp_needed = next_level_xp - current_level_xp

    percent = 100.0 if xp_needed <= 0 else (xp_in_level / xp_needed) * 100
    bar = shaded_bar(percent, DEFAULT_SIZE)
    return f"`{bar}` {xp_in_level}/{xp_needed} XP"


def format_skills_message(
    skills: list[UserSkill],
    total_level: int,
    display_name: str,
    deltas: dict[Skill, int] | None = None,
) -> str:
    """Format the full skills overview message.

    Uses a compact two-line layout per skill with a shaded progress bar
    wrapped in inline code ticks for consistent rendering.

    Args:
        skills: List of UserSkill instances
        total_level: Sum of all skill levels
        display_name: Player's display name
        deltas: Optional map of skill to XP gained, shown as (+N) indicator

    Returns:
        Formatted Discord message string
    """
    lines = [f"# {display_name}", ""]

    skill_map = {s.skill: s for s in skills}

    for skill_enum in Skill:
        user_skill = skill_map.get(str(skill_enum))
        if user_skill is None:
            level = 1
            xp = 0
        else:
            level = user_skill.level
            xp = user_skill.xp

        bar = format_progress_bar(xp, level)
        delta = deltas.get(skill_enum, 0) if deltas else 0
        if delta:
            bar = f"{bar} (+{delta}) \U0001f199"
        lines.append(f"{ViewSkill(skill_enum)} LV{level}")
        lines.append(bar)
        lines.append("")

    # newline at end to (edited) goes to bottom
    return "\n".join(lines) + "\n-# -ˋˏ ༻❁༺ ˎˊ-"


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
    skill: Skill,
    new_level: int,
) -> str:
    """Format a level-up announcement message.

    Args:
        display_name: User's display name
        skill: Skill enum value
        new_level: New level achieved

    Returns:
        Formatted announcement string
    """
    skill_view = ViewSkill(skill)
    return f"**{display_name}** advanced {skill_view} to level {new_level}!"
