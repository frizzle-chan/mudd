"""Shaded Unicode progress bar generator.

Produces smooth progress bars using sub-character resolution with the
Unicode block shading characters ░▒▓█.
"""

from __future__ import annotations

SHADED = "░▒▓█"
DEFAULT_SIZE = 20


def shaded_bar(percent: float, size: int = DEFAULT_SIZE) -> str:
    """Generate a shaded Unicode progress bar.

    Uses sub-character resolution: each character position can show one of
    four shade levels (░▒▓█), giving ``size * 3`` distinct visual steps
    instead of just ``size``.

    Args:
        percent: Fill percentage (0-100), clamped to valid range.
        size: Number of character positions in the bar.

    Returns:
        A string of exactly ``size`` characters.
    """
    percent = max(0.0, min(100.0, percent))

    b_len = len(SHADED) - 1  # 3
    empty = SHADED[0]  # ░
    full = SHADED[-1]  # █

    if percent >= 100:
        return full * size

    if percent <= 0:
        return empty * size

    segment_unit = (percent / 100) * size
    su_floor = int(segment_unit)
    fractional = segment_unit - su_floor
    middlepiece = max(1, int(fractional * b_len))

    # su_floor full chars + 1 partial char, then pad with empty
    partial = SHADED[middlepiece]
    return (full * su_floor + partial).ljust(size, empty)
