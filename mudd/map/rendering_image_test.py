"""Image regression tests for mudd.map.rendering.

Uses pytest-regressions to compare rendered output against checked-in
baseline PNGs. Regenerate baselines with ``pytest --regen-all``.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from pytest_regressions.image_regression import ImageRegressionFixture

from mudd.map.rendering import generate_map_image

# The real mansion_map layers checked into the repo
_LAYERS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "worlds" / "mansion_map"
)

_ROOM_IDS = [
    "foyer",
    "sitting-room",
    "hallway",
    "restroom",
    "office",
    "gallery",
    "library",
    "screening-room",
    "banquet-hall",
    "kitchen",
    "freezer",
    "store-room",
    "lounge",
    "courtyard",
    "race-track",
]


def test_no_rooms_visited(
    image_regression: ImageRegressionFixture,
) -> None:
    """Only the base layer, no rooms revealed."""
    image_bytes = generate_map_image(set(), layers_dir=_LAYERS_DIR)
    image_regression.check(image_bytes)


def test_single_room_visited(
    image_regression: ImageRegressionFixture,
) -> None:
    """One room visited."""
    image_bytes = generate_map_image({"foyer"}, layers_dir=_LAYERS_DIR)
    image_regression.check(image_bytes)


def test_multiple_rooms_visited(
    image_regression: ImageRegressionFixture,
) -> None:
    """Several rooms visited."""
    visited = {"foyer", "hallway", "library", "kitchen"}
    image_bytes = generate_map_image(visited, layers_dir=_LAYERS_DIR)
    image_regression.check(image_bytes)


def test_all_rooms_visited(
    image_regression: ImageRegressionFixture,
) -> None:
    """All rooms visited."""
    visited = set(_ROOM_IDS)
    image_bytes = generate_map_image(visited, layers_dir=_LAYERS_DIR)
    image_regression.check(image_bytes)


def test_offline_fallback(
    image_regression: ImageRegressionFixture,
) -> None:
    """No layers directory — renders 'map offline' placeholder."""
    with TemporaryDirectory() as tmp:
        image_bytes = generate_map_image({"foyer"}, layers_dir=Path(tmp))
    image_regression.check(image_bytes)
