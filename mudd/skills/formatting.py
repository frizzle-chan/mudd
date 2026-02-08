"""Formatting utilities for skills display."""

from __future__ import annotations

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


def format_skills_message(skills: list[UserSkill], total_level: int) -> str:
    """Format the full skills overview message.

    Args:
        skills: List of UserSkill instances
        total_level: Sum of all skill levels

    Returns:
        Formatted Discord message string
    """
    lines = [f"**Total Level: {total_level}**", ""]

    # Build a lookup for ordering by Skill enum order
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
        display = skill_enum.display_name
        lines.append(f"**{display}** Lv. {level} {bar}")

    return "\n".join(lines)


def format_nickname(display_name: str, total_level: int) -> str:
    """Format a Discord nickname with total level suffix.

    Truncates display_name if the result would exceed 32 chars.

    Args:
        display_name: User's display name
        total_level: Sum of all skill levels

    Returns:
        Formatted nickname string
    """
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
