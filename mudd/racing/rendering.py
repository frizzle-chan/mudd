"""Race frame renderer.

Pure functions — no database access, no async.
Produces PIL images from race simulation snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont
from PIL.Image import Resampling

from mudd.racing.simulation import BurstEvent, RaceResult

# Layout constants
CANVAS_WIDTH = 640
NAME_MARGIN = 80
TRACK_WIDTH = 520
FINISH_X = 600
RIGHT_PADDING = 40
LANE_HEIGHT = 24
SPRITE_SIZE = 16
LANE_PADDING = 8
HEADER_HEIGHT = 20

# Colors
BG_COLOR = (35, 35, 45)
TRACK_BG = (50, 55, 65)
LANE_DIVIDER = (65, 70, 80)
FINISH_COLOR = (220, 180, 50)
TEXT_COLOR = (200, 200, 210)

# Fallback sprite palette
_FALLBACK_COLORS = [
    (220, 60, 60),
    (60, 160, 220),
    (60, 200, 80),
    (220, 180, 50),
    (180, 80, 220),
    (220, 130, 50),
    (80, 220, 200),
    (220, 80, 160),
]


@dataclass(frozen=True, slots=True)
class RaceHorse:
    """A horse with a name and sprite for rendering."""

    name: str
    sprite: Image.Image  # 16x16 RGBA


def sample_frames(snapshots: list[list[float]], render_frames: int = 12) -> list[int]:
    """Return tick indices for evenly-spaced frames including first and last.

    Returns render_frames + 1 indices (e.g. 13 for render_frames=12).
    """
    total_ticks = len(snapshots) - 1
    if total_ticks <= 0:
        return [0]
    step = total_ticks / render_frames
    return [round(i * step) for i in range(render_frames + 1)]


def sprite_from_bytes(data: bytes) -> Image.Image:
    """Convert PNG bytes to a 16x16 RGBA PIL Image."""
    from io import BytesIO

    img = Image.open(BytesIO(data))
    img = img.convert("RGBA")
    img = img.resize((SPRITE_SIZE, SPRITE_SIZE), Resampling.NEAREST)
    return img


def fallback_sprite(index: int) -> Image.Image:
    """Generate a solid-color 16x16 placeholder sprite."""
    color = _FALLBACK_COLORS[index % len(_FALLBACK_COLORS)]
    img = Image.new("RGBA", (SPRITE_SIZE, SPRITE_SIZE), (*color, 255))
    return img


def render_frame(
    horses: list[RaceHorse],
    positions: list[float],
    events: list[BurstEvent],
    tick: int,
    frame_index: int,
    total_frames: int,
) -> Image.Image:
    """Render a single race frame.

    Args:
        horses: Horse names and sprites.
        positions: Normalized positions (0.0 to 1.0) for each horse.
        events: Burst events (accepted for forward compat, not rendered yet).
        tick: The simulation tick this frame represents.
        frame_index: 0-based index of this frame in the sequence.
        total_frames: Total number of frames being rendered.

    Returns:
        A single frame as an RGBA PIL Image.
    """
    n = len(horses)
    frame_height = HEADER_HEIGHT + n * LANE_HEIGHT
    img = Image.new("RGBA", (CANVAS_WIDTH, frame_height), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img)

    header_font = ImageFont.load_default(size=11)
    name_font = ImageFont.load_default(size=14)

    # Header
    header_text = f"Tick {tick}  ({frame_index + 1}/{total_frames})"
    draw.text((4, 2), header_text, fill=TEXT_COLOR, font=header_font)

    # Track background
    track_y = HEADER_HEIGHT
    track_h = n * LANE_HEIGHT
    draw.rectangle(
        [NAME_MARGIN, track_y, NAME_MARGIN + TRACK_WIDTH, track_y + track_h],
        fill=TRACK_BG,
    )

    # Lane dividers
    for i in range(1, n):
        y = track_y + i * LANE_HEIGHT
        draw.line(
            [(NAME_MARGIN, y), (NAME_MARGIN + TRACK_WIDTH, y)],
            fill=LANE_DIVIDER,
            width=1,
        )

    # Finish line (2px wide)
    draw.line(
        [(FINISH_X, track_y), (FINISH_X, track_y + track_h)],
        fill=FINISH_COLOR,
        width=2,
    )

    # Horses
    for i, horse in enumerate(horses):
        lane_y = track_y + i * LANE_HEIGHT

        # Name label
        draw.text(
            (4, lane_y + (LANE_HEIGHT - 14) // 2),
            horse.name[:10],
            fill=TEXT_COLOR,
            font=name_font,
        )

        # Sprite position: map 0.0-1.0 to NAME_MARGIN .. FINISH_X
        x = NAME_MARGIN + int(positions[i] * (FINISH_X - NAME_MARGIN - SPRITE_SIZE))
        sprite_y = lane_y + (LANE_HEIGHT - SPRITE_SIZE) // 2
        img.paste(horse.sprite, (x, sprite_y), horse.sprite)

    return img


def render_race(
    horses: list[RaceHorse],
    result: RaceResult,
    render_frames: int = 12,
) -> list[Image.Image]:
    """Sample frames from a race result and render each one.

    Args:
        horses: Horse names and sprites (must align with result.horse_ids).
        result: The simulation result containing snapshots and events.
        render_frames: Number of intervals to sample
            (produces render_frames + 1 frames).

    Returns:
        List of rendered frame images.
    """
    ticks = sample_frames(result.snapshots, render_frames)
    total = len(ticks)
    frames: list[Image.Image] = []

    for frame_idx, tick in enumerate(ticks):
        positions = result.snapshots[tick]
        tick_events = [e for e in result.events if e.tick == tick]
        frame = render_frame(horses, positions, tick_events, tick, frame_idx, total)
        frames.append(frame)

    return frames


def tile_frames(frames: list[Image.Image], gap: int = 4) -> Image.Image:
    """Stack frames vertically into one tall PNG.

    Args:
        frames: List of frame images (all same width).
        gap: Pixel gap between frames.

    Returns:
        A single RGBA image with all frames tiled vertically.
    """
    if not frames:
        return Image.new("RGBA", (CANVAS_WIDTH, 1), BG_COLOR + (255,))

    width = frames[0].width
    total_height = sum(f.height for f in frames) + gap * (len(frames) - 1)
    tiled = Image.new("RGBA", (width, total_height), BG_COLOR + (255,))

    y = 0
    for frame in frames:
        tiled.paste(frame, (0, y))
        y += frame.height + gap

    return tiled
