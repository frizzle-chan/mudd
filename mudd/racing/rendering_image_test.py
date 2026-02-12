"""Image regression tests for mudd.racing.rendering.

Uses pytest-regressions to compare rendered output against checked-in
baseline PNGs. Regenerate baselines with ``pytest --regen-all``.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image
from pytest_regressions.image_regression import ImageRegressionFixture

from mudd.racing.rendering import (
    PROFILE_SIZE,
    AnnouncementHorse,
    RaceHorse,
    fallback_sprite,
    render_announcement,
    render_frame,
    render_winner,
    tile_frames,
)
from mudd.racing.simulation import RaceResult

_HORSE_NAMES = ["Stardust", "Crimson", "Oceanic", "Gilded"]
_PROFILE_COLORS = [
    (220, 60, 60, 255),
    (60, 160, 220, 255),
    (60, 200, 80, 255),
    (220, 180, 50, 255),
]


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
            AnnouncementHorse(horse_id=f"horse_{i}", name=name, profile=profile)
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


def test_render_frame(image_regression: ImageRegressionFixture) -> None:
    horses = _make_race_horses()
    positions = [0.0, 0.33, 0.66, 1.0]
    frame = render_frame(horses, positions, [], tick=30, frame_index=6, total_frames=13)
    image_regression.check(_to_png(frame))


def test_render_announcement(image_regression: ImageRegressionFixture) -> None:
    horses = _make_announcement_horses()
    odds = [2.5, 4.0, 6.5, 10.0]
    forms = ["W-W-P", "P-L-W", "L-L-P", "W-P-W"]
    star_ratings = [
        "\u2605\u2605\u2605\u2606\u2606",
        "\u2605\u2605\u2606\u2606\u2606",
        "\u2605\u2606\u2606\u2606\u2606",
        "\u2605\u2605\u2605\u2605\u2606",
    ]
    image_data = render_announcement(horses, odds, forms, star_ratings, race_number=7)
    image_regression.check(image_data)


def test_render_winner(image_regression: ImageRegressionFixture) -> None:
    victory_image = _make_victory_image()
    image_data = render_winner(victory_image, "Stardust", race_number=7)
    image_regression.check(image_data)


def test_tile_frames(image_regression: ImageRegressionFixture) -> None:
    horses = _make_race_horses()
    n_ticks = 60
    snapshots: list[list[float]] = []
    for t in range(n_ticks + 1):
        frac = t / n_ticks
        snapshots.append([frac * (1 - i * 0.05) for i in range(len(horses))])
    result = RaceResult(
        snapshots=snapshots,
        events=[],
        finishing_order=list(range(len(horses))),
        horse_ids=[f"horse_{i}" for i in range(len(horses))],
    )

    from mudd.racing.rendering import render_race

    frames = render_race(horses, result, render_frames=4)
    tiled = tile_frames(frames)
    image_regression.check(_to_png(tiled))
