"""Race configuration and tuning constants."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RaceConfig:
    """All tuning constants for the racing simulation.

    See horse.local.md § Tuning Constants for documentation.
    """

    house_edge: float = 0.10
    odds_exponent: float = 2.0
    rolling_window: int = 20
    num_ticks: int = 60
    rubber_band_factor: float = 0.05
    burst_chance: float = 0.05
    burst_surge_mult: float = 1.5
    burst_stumble_mult: float = 0.5
    fatigue_onset: float = 0.6
    fatigue_severity: float = 0.15
    noise_factor: float = 0.3
    form_variance: float = 1.0
    progress_scale: float = 2.0


DEFAULT_CONFIG = RaceConfig()
