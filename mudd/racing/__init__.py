"""Horse racing simulation engine.

Reusable package for odds calculation, race simulation, and persistence.
Imported by both the CLI tool and the Discord cog.
"""

from mudd.racing.config import DEFAULT_CONFIG, RaceConfig
from mudd.racing.odds import HorseOdds, HorseStats, compute_odds
from mudd.racing.rendering import (
    RaceHorse,
    render_frame,
    render_race,
    sprite_from_bytes,
    tile_frames,
)
from mudd.racing.simulation import BurstEvent, BurstType, RaceResult, simulate_race

__all__ = [
    "BurstEvent",
    "BurstType",
    "DEFAULT_CONFIG",
    "HorseOdds",
    "HorseStats",
    "RaceConfig",
    "RaceHorse",
    "RaceResult",
    "compute_odds",
    "render_frame",
    "render_race",
    "simulate_race",
    "sprite_from_bytes",
    "tile_frames",
]
