"""Horse racing simulation engine.

Reusable package for odds calculation, race simulation, and persistence.
Imported by both the CLI tool and the Discord cog.
"""

from mudd.racing.config import DEFAULT_CONFIG, RaceConfig
from mudd.racing.odds import HorseOdds, HorseStats, compute_odds
from mudd.racing.simulation import BurstEvent, BurstType, RaceResult, simulate_race

__all__ = [
    "BurstEvent",
    "BurstType",
    "DEFAULT_CONFIG",
    "HorseOdds",
    "HorseStats",
    "RaceConfig",
    "RaceResult",
    "compute_odds",
    "simulate_race",
]
