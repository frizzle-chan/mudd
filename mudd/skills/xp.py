"""OSRS-style XP formula for the skills system.

Pre-computes the XP table at module load for fast lookups.
Formula: xp_for_level(L) = floor(sum(floor(i + 300 * 2^(i/7)) for i in 1..L-1) / 4)
"""

from __future__ import annotations

import math

MAX_LEVEL: int = 99
MAX_XP: int = 200_000_000

# Pre-computed cumulative XP required for each level (index 0 unused, 1-99)
_XP_TABLE: list[int] = [0] * (MAX_LEVEL + 1)


def _build_xp_table() -> None:
    """Build the XP table using the OSRS formula."""
    cumulative = 0.0
    _XP_TABLE[1] = 0  # Level 1 requires 0 XP
    for i in range(1, MAX_LEVEL):
        cumulative += math.floor(i + 300 * 2 ** (i / 7))
        _XP_TABLE[i + 1] = math.floor(cumulative / 4)


_build_xp_table()


def xp_for_level(level: int) -> int:
    """Return the cumulative XP required to reach the given level.

    Args:
        level: Target level (1-99)

    Returns:
        Cumulative XP required for that level

    Raises:
        ValueError: If level is outside 1-99
    """
    if level < 1 or level > MAX_LEVEL:
        raise ValueError(f"Level must be between 1 and {MAX_LEVEL}, got {level}")
    return _XP_TABLE[level]


def level_for_xp(xp: int) -> int:
    """Return the current level for the given cumulative XP.

    Uses binary search over the pre-computed XP table.

    Args:
        xp: Current cumulative XP (0 to MAX_XP)

    Returns:
        Current level (1-99)

    Raises:
        ValueError: If xp is negative
    """
    if xp < 0:
        raise ValueError(f"XP must be non-negative, got {xp}")

    # Binary search: find highest level whose XP requirement is <= xp
    low, high = 1, MAX_LEVEL
    while low < high:
        mid = (low + high + 1) // 2
        if _XP_TABLE[mid] <= xp:
            low = mid
        else:
            high = mid - 1
    return low
