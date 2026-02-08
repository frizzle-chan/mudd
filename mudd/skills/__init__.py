"""Skills progression system for MUDD.

OSRS-style XP curve with passive skill training via game events.
"""

from mudd.skills.registry import SKILL_COUNT, Skill
from mudd.skills.xp import MAX_LEVEL, MAX_XP, level_for_xp, xp_for_level

__all__ = [
    "MAX_LEVEL",
    "MAX_XP",
    "SKILL_COUNT",
    "Skill",
    "level_for_xp",
    "xp_for_level",
]
