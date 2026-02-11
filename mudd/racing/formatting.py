"""Text formatting for racing CLI output.

Pure functions — no database access, no async.
"""

from __future__ import annotations

from mudd.racing.odds import HorseOdds


def format_form(results: list[int], count: int = 5) -> str:
    """Format recent race positions as a form string.

    Args:
        results: Finishing positions, newest first.
        count: Maximum number of results to show.

    Returns:
        String like "W-P-L-W-P". W=1st, P=2nd/3rd, L=4th+.
        Returns "—" for empty history.
    """
    if not results:
        return "—"
    # Take up to `count` most recent, then reverse so oldest is on left
    recent = results[:count][::-1]
    parts: list[str] = []
    for pos in recent:
        if pos == 1:
            parts.append("W")
        elif pos <= 3:
            parts.append("P")
        else:
            parts.append("L")
    return "-".join(parts)


def format_star_rating(stars: int) -> str:
    """Format a 1–5 star rating as filled/empty stars.

    Returns a 5-character string like "★★★☆☆".
    """
    return "★" * stars + "☆" * (5 - stars)


def format_odds_board(
    odds: list[HorseOdds],
    forms: dict[str, list[int]],
    names: dict[str, str],
) -> str:
    """Format the full odds board for display.

    Args:
        odds: Computed odds for each horse.
        forms: Mapping of horse_id to recent positions (newest first).
        names: Mapping of horse_id to display name.
    """
    header = f"  {'Horse':<14} {'Odds':>8}     {'Form':<11} {'Rating'}"
    separator = "  " + "─" * 50
    lines = [header, separator]
    for o in odds:
        name = names.get(o.horse_id, o.horse_id)
        form = format_form(forms.get(o.horse_id, []))
        rating = format_star_rating(o.star_rating)
        lines.append(
            f"  {name:<14} {o.displayed_payout:>5.1f}:1    {form:<11} {rating}"
        )
    return "\n".join(lines)


def format_results(
    finishing_order: list[int],
    horse_names: list[str],
    odds: list[HorseOdds],
) -> str:
    """Format the finishing order as a results table.

    Args:
        finishing_order: Horse indices by final position.
        horse_names: Names aligned with horse indices.
        odds: Odds aligned with horse indices.
    """
    labels = ["1st", "2nd", "3rd"]
    lines: list[str] = []
    for rank, idx in enumerate(finishing_order):
        label = labels[rank] if rank < len(labels) else f"{rank + 1}th"
        name = horse_names[idx]
        payout = odds[idx].displayed_payout
        lines.append(f"  {label:<4} {name:<14} {payout:.1f}:1")
    return "\n".join(lines)
