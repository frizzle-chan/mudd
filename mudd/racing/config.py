"""Race configuration and tuning constants."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RaceConfig:
    """All tuning constants for the racing simulation.

    See horse.local.md § Tuning Constants for documentation.
    """

    # Scheduling
    race_hour: int = 16  # 4:20 PM Central = race start time
    race_minute: int = 20
    race_timezone: str = "America/Chicago"
    pre_race_minutes: int = 60  # announcement posted this many minutes before
    discord_event_lead_minutes: int = 10  # Discord event starts this early before race

    # Simulation
    house_edge: float = 0.10
    odds_exponent: float = 4.5
    rolling_window: int = 20
    num_ticks: int = 0  # 0 = auto-derive from race_duration_minutes
    rubber_band_factor: float = 0.05
    burst_chance: float = 0.05
    burst_surge_mult: float = 1.5
    burst_stumble_mult: float = 0.5
    fatigue_onset: float = 0.6
    fatigue_severity: float = 0.15
    noise_factor: float = 0.3
    form_variance: float = 0.3
    progress_scale: float = 2.0
    progress_floor: float = 0.1
    race_duration_minutes: float = 3.0
    gif_interval_seconds: int = 15
    frames_per_gif: int = 6
    frame_duration_ms: int = 800
    ticks_per_frame: float = 2.5

    def __post_init__(self) -> None:
        if self.num_ticks == 0:
            object.__setattr__(
                self,
                "num_ticks",
                round(self.total_render_frames * self.ticks_per_frame),
            )

    @property
    def num_gifs(self) -> int:
        return max(
            2, round(self.race_duration_minutes * 60 / self.gif_interval_seconds)
        )

    @property
    def total_render_frames(self) -> int:
        return self.num_gifs * self.frames_per_gif

    @property
    def frame_batches(self) -> list[list[int]]:
        return [
            list(range(i * self.frames_per_gif, (i + 1) * self.frames_per_gif))
            for i in range(self.num_gifs)
        ]


# Room where races happen and bets can be placed
RACE_TRACK_ROOM = "race-track"

DEFAULT_CONFIG = RaceConfig()
