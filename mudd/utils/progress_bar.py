"""Shaded Unicode progress bar generator.

Produces smooth progress bars using sub-character resolution with the
Unicode block shading characters ░▒▓█.
"""

from __future__ import annotations

SHADED = "░▒▓█"
DEFAULT_SIZE = 16


def shaded_bar(percent: float, size: int = DEFAULT_SIZE) -> str:
    """Generate a shaded Unicode progress bar.

    Uses sub-character resolution: each character position can show one of
    four shade levels (░▒▓█), providing much smoother visual feedback than
    a simple binary filled/unfilled bar.

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

    # If there's no fractional part, no partial character needed
    if fractional == 0:
        return (full * su_floor).ljust(size, empty)

    # Otherwise, add a partial character based on the fractional value
    shade_index = int(fractional * b_len)
    if shade_index == 0:
        shade_index = 1  # Ensure at least light shade for any fractional value

    partial = SHADED[shade_index]
    return (full * su_floor + partial).ljust(size, empty)
