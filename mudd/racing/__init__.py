"""Horse racing simulation engine.

Reusable package for odds calculation, race simulation, and persistence.
Imported by both the CLI tool and the Discord cog.
"""

from mudd.racing.config import DEFAULT_CONFIG, RaceConfig
from mudd.racing.odds import HorseOdds, HorseStats, compute_odds
from mudd.racing.rendering import (
    AnnouncementHorse,
    RaceHorse,
    profile_from_bytes,
    render_announcement,
    render_frame,
    render_race,
    render_race_gif,
    render_winner,
    sprite_from_bytes,
    tile_frames,
)
from mudd.racing.simulation import BurstEvent, BurstType, RaceResult, simulate_race

__all__ = [
    "AnnouncementHorse",
    "BurstEvent",
    "BurstType",
    "DEFAULT_CONFIG",
    "HorseOdds",
    "HorseStats",
    "RaceConfig",
    "RaceHorse",
    "RaceResult",
    "compute_odds",
    "profile_from_bytes",
    "render_announcement",
    "render_frame",
    "render_race",
    "render_race_gif",
    "render_winner",
    "simulate_race",
    "sprite_from_bytes",
    "tile_frames",
]
