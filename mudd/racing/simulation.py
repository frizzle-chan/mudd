"""Race simulation engine.

Pure functions — no database access, no async.
Accepts a Random instance for deterministic results.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from random import Random

from mudd.racing.config import DEFAULT_CONFIG, RaceConfig
from mudd.racing.odds import HorseStats


class BurstType(StrEnum):
    """Type of burst event during a race."""

    SURGE = "surge"
    STUMBLE = "stumble"


@dataclass(frozen=True, slots=True)
class BurstEvent:
    """A burst event that occurred during the race."""

    tick: int
    horse_index: int
    burst_type: BurstType


@dataclass(frozen=True, slots=True)
class RaceResult:
    """Full simulation output.

    Attributes:
        snapshots: Position matrix — list of (num_ticks+1) frames,
            each frame is a list of floats (one per horse).
        events: Burst events that occurred during the race.
        finishing_order: Horse indices sorted by final position (winner first).
        horse_ids: Horse IDs aligned with snapshot indices.
    """

    snapshots: list[list[float]]
    events: list[BurstEvent]
    finishing_order: list[int]
    horse_ids: list[str]


# Phase weights: (speed, stamina, luck)
_START_WEIGHTS = (0.3, 0.1, 0.6)
_MIDDLE_WEIGHTS = (0.6, 0.2, 0.2)
_FINAL_WEIGHTS = (0.2, 0.6, 0.2)


def _phase_weights(phase: float) -> tuple[float, float, float]:
    """Return (speed, stamina, luck) weights for the given phase fraction."""
    if phase <= 0.2:
        return _START_WEIGHTS
    if phase <= 0.7:
        return _MIDDLE_WEIGHTS
    return _FINAL_WEIGHTS


def simulate_race(
    horses: list[HorseStats],
    rng: Random | None = None,
    config: RaceConfig = DEFAULT_CONFIG,
) -> RaceResult:
    """Run a full race simulation.

    Args:
        horses: Stats for each horse in the race.
        rng: Random instance for determinism. Uses default Random if None.
        config: Tuning constants.

    Returns:
        Complete race result with snapshots, events, and finishing order.
    """
    if rng is None:
        rng = Random()

    n = len(horses)
    positions = [0.0] * n
    snapshots: list[list[float]] = [list(positions)]
    events: list[BurstEvent] = []

    # Per-phase form factors: how each horse performs in each race phase.
    # Three independent draws create natural lead changes — a horse can
    # start strong then fade, or come from behind in the final stretch.
    # Form variance is uniform across horses (race-day luck). Consistency
    # only affects per-tick noise, not race-day form.
    form_per_phase = [
        (
            rng.gauss(0, config.form_variance),
            rng.gauss(0, config.form_variance),
            rng.gauss(0, config.form_variance),
        )
        for _ in horses
    ]

    for tick in range(1, config.num_ticks + 1):
        phase = tick / config.num_ticks
        w_speed, w_stamina, w_luck = _phase_weights(phase)

        # Select form bonus for current phase
        if phase <= 0.2:
            phase_idx = 0
        elif phase <= 0.7:
            phase_idx = 1
        else:
            phase_idx = 2

        avg_pos = sum(positions) / n

        for i, h in enumerate(horses):
            # Weighted base progress (stats normalized to 0–1)
            base = (
                (h.speed / 100.0) * w_speed
                + (h.stamina / 100.0) * w_stamina
                + (h.luck / 100.0) * w_luck
                + form_per_phase[i][phase_idx]
            )

            # Gaussian noise scaled by inconsistency (floor of 0.2 prevents
            # high-consistency horses from being perfectly deterministic)
            noise_scale = max(0.2, (100 - h.consistency) / 100.0)
            noise = rng.gauss(0, noise_scale * config.noise_factor)

            # Clamp base + noise to >= 0
            progress = max(0.0, base + noise)

            # Fatigue penalty after onset
            if phase > config.fatigue_onset:
                fatigue_pct = (phase - config.fatigue_onset) / (
                    1.0 - config.fatigue_onset
                )
                fatigue = config.fatigue_severity * fatigue_pct * (1 - h.stamina / 100)
                progress *= 1.0 - fatigue

            # Burst events
            if rng.random() < config.burst_chance:
                if rng.random() < 0.5:
                    burst_type = BurstType.SURGE
                    progress *= config.burst_surge_mult
                else:
                    burst_type = BurstType.STUMBLE
                    progress *= config.burst_stumble_mult
                events.append(
                    BurstEvent(tick=tick, horse_index=i, burst_type=burst_type)
                )

            # Scale by progress_scale / num_ticks
            progress *= config.progress_scale / config.num_ticks

            # Rubber-banding (applied to scaled progress per spec)
            rubber_band = (avg_pos - positions[i]) * config.rubber_band_factor
            progress += rubber_band

            # No backward movement
            positions[i] = max(positions[i], positions[i] + progress)

        snapshots.append(list(positions))

    # Normalize so winner finishes at 1.0
    max_pos = max(positions)
    if max_pos > 0:
        scale = 1.0 / max_pos
        snapshots = [[p * scale for p in frame] for frame in snapshots]

    # Determine finishing order from final positions (descending)
    final = snapshots[-1]
    finishing_order = sorted(range(n), key=lambda i: final[i], reverse=True)

    return RaceResult(
        snapshots=snapshots,
        events=events,
        finishing_order=finishing_order,
        horse_ids=[h.horse_id for h in horses],
    )
