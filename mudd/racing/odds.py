"""Odds calculation for horse racing.

Pure functions — no database access, no async.
"""

from __future__ import annotations

from dataclasses import dataclass

from mudd.racing.config import DEFAULT_CONFIG, RaceConfig


@dataclass(frozen=True, slots=True)
class HorseStats:
    """Lightweight projection of a Horse model for odds/simulation use."""

    horse_id: str
    speed: int
    stamina: int
    consistency: int
    luck: int
    recent_races: int
    recent_wins: int
    recent_places: int


@dataclass(frozen=True, slots=True)
class HorseOdds:
    """Computed odds for a single horse."""

    horse_id: str
    base_strength: float
    performance_modifier: float
    dynamic_strength: float
    true_probability: float
    displayed_payout: float
    star_rating: int


def base_strength(speed: int, stamina: int, luck: int, consistency: int) -> float:
    """Compute static base strength from attributes.

    Formula: speed*0.5 + stamina*0.3 + luck*0.1 + consistency*0.1
    """
    return speed * 0.5 + stamina * 0.3 + luck * 0.1 + consistency * 0.1


def performance_modifier(
    base: float, total_base: float, recent_wins: int, recent_races: int
) -> float:
    """Compute dynamic performance modifier from recent history.

    Returns 1.0 when no race history exists.
    """
    if recent_races == 0:
        return 1.0
    expected_win_rate = base / total_base
    actual_win_rate = recent_wins / recent_races
    return 1.0 + (actual_win_rate - expected_win_rate) * 0.5


def compute_odds(
    horses: list[HorseStats], config: RaceConfig = DEFAULT_CONFIG
) -> list[HorseOdds]:
    """Compute full odds for all horses in a race.

    Pipeline: base strength → performance modifier → dynamic strength →
    true probability → displayed payout → star rating.
    """
    # Base strengths
    bases = [base_strength(h.speed, h.stamina, h.luck, h.consistency) for h in horses]
    total_base = sum(bases)

    # Performance modifiers
    modifiers = [
        performance_modifier(b, total_base, h.recent_wins, h.recent_races)
        for b, h in zip(bases, horses, strict=True)
    ]

    # Dynamic strengths
    dynamics = [b * m for b, m in zip(bases, modifiers, strict=True)]
    total_dynamic = sum(dynamics)

    # True probabilities
    probabilities = [d / total_dynamic for d in dynamics]

    # Displayed payouts (with house edge)
    payouts = [(1.0 / p) * (1.0 - config.house_edge) for p in probabilities]

    # Star ratings (relative to max dynamic strength)
    max_dynamic = max(dynamics)
    ratings = [_star_rating(d / max_dynamic) for d in dynamics]

    return [
        HorseOdds(
            horse_id=h.horse_id,
            base_strength=b,
            performance_modifier=m,
            dynamic_strength=d,
            true_probability=p,
            displayed_payout=pay,
            star_rating=r,
        )
        for h, b, m, d, p, pay, r in zip(
            horses,
            bases,
            modifiers,
            dynamics,
            probabilities,
            payouts,
            ratings,
            strict=True,
        )
    ]


def _star_rating(ratio: float) -> int:
    """Convert a dynamic-strength ratio (0–1) to a 1–5 star rating."""
    if ratio >= 0.8:
        return 5
    if ratio >= 0.6:
        return 4
    if ratio >= 0.4:
        return 3
    if ratio >= 0.2:
        return 2
    return 1
