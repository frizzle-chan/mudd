"""Full-pipeline race integration test.

Exercises stats → odds → simulation → rendering with deterministic inputs.
Uses image regression for visual output and assertions for structural properties.
"""

from __future__ import annotations

from io import BytesIO
from random import Random

from PIL import Image
from pytest_regressions.image_regression import ImageRegressionFixture

from mudd.racing.config import DEFAULT_CONFIG
from mudd.racing.formatting import format_form, format_star_rating
from mudd.racing.odds import HorseStats, compute_odds
from mudd.racing.rendering import (
    PROFILE_SIZE,
    AnnouncementHorse,
    RaceHorse,
    fallback_sprite,
    render_announcement,
    render_frame,
    render_race,
    render_race_gif,
    render_winner,
    sample_frames,
    tile_frames,
)
from mudd.racing.simulation import simulate_race

# ---------------------------------------------------------------------------
# Module-level setup (computed once on import)
# ---------------------------------------------------------------------------

_HORSE_NAMES = ["Stardust", "Crimson", "Oceanic", "Gilded"]
_PROFILE_COLORS = [
    (220, 60, 60, 255),
    (60, 160, 220, 255),
    (60, 200, 80, 255),
    (220, 180, 50, 255),
]

_STATS = [
    HorseStats(
        horse_id="stardust",
        speed=85,
        stamina=70,
        consistency=80,
        luck=60,
        recent_races=10,
        recent_wins=4,
        recent_places=2,
    ),
    HorseStats(
        horse_id="crimson",
        speed=60,
        stamina=90,
        consistency=65,
        luck=75,
        recent_races=8,
        recent_wins=1,
        recent_places=3,
    ),
    HorseStats(
        horse_id="oceanic",
        speed=75,
        stamina=75,
        consistency=90,
        luck=50,
        recent_races=12,
        recent_wins=3,
        recent_places=4,
    ),
    HorseStats(
        horse_id="gilded",
        speed=95,
        stamina=55,
        consistency=50,
        luck=85,
        recent_races=6,
        recent_wins=3,
        recent_places=1,
    ),
]

# Recent finishing positions for form display (newest first)
_RECENT_RESULTS: dict[str, list[int]] = {
    "stardust": [1, 2, 1, 3, 1],
    "crimson": [4, 3, 2, 5, 1],
    "oceanic": [2, 1, 3, 1, 2],
    "gilded": [1, 1, 4, 2, 1],
}

_ODDS = compute_odds(_STATS, DEFAULT_CONFIG)
_RESULT = simulate_race(_STATS, rng=Random(42), config=DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_race_horses() -> list[RaceHorse]:
    return [
        RaceHorse(name=name, sprite=fallback_sprite(i))
        for i, name in enumerate(_HORSE_NAMES)
    ]


def _make_announcement_horses() -> list[AnnouncementHorse]:
    horses: list[AnnouncementHorse] = []
    for i, name in enumerate(_HORSE_NAMES):
        profile = Image.new("RGBA", (PROFILE_SIZE, PROFILE_SIZE), _PROFILE_COLORS[i])
        horses.append(
            AnnouncementHorse(horse_id=_STATS[i].horse_id, name=name, profile=profile)
        )
    return horses


def _make_victory_image() -> bytes:
    img = Image.new("RGBA", (128, 128), (220, 180, 50, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _to_png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_simulation_structural_properties() -> None:
    """Verify simulation output invariants."""
    snapshots = _RESULT.snapshots
    n_horses = len(_STATS)

    # Snapshot count = num_ticks + 1
    assert len(snapshots) == DEFAULT_CONFIG.num_ticks + 1

    # All horses start at 0.0
    for pos in snapshots[0]:
        assert pos == 0.0

    # Winner finishes at exactly 1.0
    winner_idx = _RESULT.finishing_order[0]
    assert snapshots[-1][winner_idx] == 1.0

    # finishing_order is a valid permutation
    assert sorted(_RESULT.finishing_order) == list(range(n_horses))

    # Positions are monotonically non-decreasing for each horse
    for h in range(n_horses):
        for t in range(1, len(snapshots)):
            assert snapshots[t][h] >= snapshots[t - 1][h], (
                f"Horse {h} moved backwards at tick {t}"
            )

    # horse_ids match input stats
    assert _RESULT.horse_ids == [s.horse_id for s in _STATS]


def test_odds_structural_properties() -> None:
    """Verify odds computation invariants."""
    # Probabilities sum to ~1.0
    total_prob = sum(o.true_probability for o in _ODDS)
    assert abs(total_prob - 1.0) < 1e-9

    # All payouts positive
    for o in _ODDS:
        assert o.displayed_payout > 0

    # Star ratings in [1, 5]
    for o in _ODDS:
        assert 1 <= o.star_rating <= 5

    # Performance modifiers are exercised (not all 1.0)
    modifiers = [o.performance_modifier for o in _ODDS]
    assert not all(m == 1.0 for m in modifiers)


# ---------------------------------------------------------------------------
# Image regression tests
# ---------------------------------------------------------------------------


def test_announcement(image_regression: ImageRegressionFixture) -> None:
    """Announcement image from computed odds, forms, and star ratings."""
    horses = _make_announcement_horses()
    odds = [o.displayed_payout for o in _ODDS]
    forms = [format_form(_RECENT_RESULTS[s.horse_id]) for s in _STATS]
    star_ratings = [format_star_rating(o.star_rating) for o in _ODDS]
    image_data = render_announcement(horses, odds, forms, star_ratings, race_number=1)
    image_regression.check(image_data)


def test_race_gif_batch() -> None:
    """First GIF batch has valid format and correct frame count."""
    horses = _make_race_horses()
    first_batch = DEFAULT_CONFIG.frame_batches[0]
    gif_data = render_race_gif(
        horses,
        _RESULT,
        first_batch,
        frame_duration_ms=DEFAULT_CONFIG.frame_duration_ms,
        render_frames=DEFAULT_CONFIG.total_render_frames,
    )

    # Valid GIF magic bytes
    assert gif_data[:6] in (b"GIF87a", b"GIF89a")

    # Correct frame count
    gif = Image.open(BytesIO(gif_data))
    assert getattr(gif, "n_frames", 1) == len(first_batch)


def test_photo_finish(image_regression: ImageRegressionFixture) -> None:
    """Last sampled frame using full total_render_frames path."""
    horses = _make_race_horses()
    ticks = sample_frames(_RESULT.snapshots, DEFAULT_CONFIG.total_render_frames)
    last_tick = ticks[-1]
    positions = _RESULT.snapshots[last_tick]
    frame = render_frame(
        horses,
        positions,
        [],
        tick=last_tick,
        frame_index=len(ticks) - 1,
        total_frames=len(ticks),
    )
    image_regression.check(_to_png(frame))


def test_winner(image_regression: ImageRegressionFixture) -> None:
    """Winner image using actual simulation winner's name."""
    winner_idx = _RESULT.finishing_order[0]
    winner_name = _HORSE_NAMES[winner_idx]
    victory_image = _make_victory_image()
    image_data = render_winner(victory_image, winner_name, race_number=1)
    image_regression.check(image_data)


def test_tiled_frames(image_regression: ImageRegressionFixture) -> None:
    """Tiled frames from render_race with render_frames=12."""
    horses = _make_race_horses()
    frames = render_race(horses, _RESULT, render_frames=12)
    tiled = tile_frames(frames)
    image_regression.check(_to_png(tiled))
