"""Betting formatting utilities for horse races."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mudd.models.bet import PayoutRecord


def format_payout_message(payouts: list[PayoutRecord]) -> str:
    """Format betting results for posting to the race thread."""
    if not payouts:
        return ""

    winners = [p for p in payouts if p.payout > 0]
    losers = [p for p in payouts if p.payout == 0]

    lines: list[str] = ["### Betting Results\n"]

    if winners:
        lines.append("Winners:")
        for p in winners:
            lines.append(
                f"\U0001f4b9 <@{p.user_id}> bet \u00a4{p.amount_bet:,} on "
                f"**{p.horse_name}** and won **\u00a4{p.payout:,}**!"
            )

    if losers:
        lines.append("Losers:")
        for p in losers:
            lines.append(
                f"\U0001f53b <@{p.user_id}> bet \u00a4{p.amount_bet:,} on "
                f"**{p.horse_name}** and lost."
            )

    return "\n".join(lines)
