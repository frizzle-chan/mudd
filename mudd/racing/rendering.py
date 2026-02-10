"""Race frame renderer.

Pure functions — no database access, no async.
Produces PIL images from race simulation snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from PIL.Image import Resampling

from mudd.racing.simulation import BurstEvent, RaceResult

# Font path — UnifontEX monospace installed in the Docker image
_FONT_PATH = "/usr/share/fonts/truetype/unifontex/unifontex.ttf"


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load UnifontEX at the given size, falling back to default."""
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


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
HEADER_TEXT_COLOR = (90, 95, 105)

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

    header_font = _load_font(13)
    name_font = _load_font(14)

    # Header
    header_text = f"Tick {tick}  ({frame_index + 1}/{total_frames})"
    draw.text((4, 2), header_text, fill=HEADER_TEXT_COLOR, font=header_font)

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


# ---------------------------------------------------------------------------
# Announcement image
# ---------------------------------------------------------------------------

PROFILE_SIZE = 64
ANNOUNCEMENT_ROW_HEIGHT = 80
ANNOUNCEMENT_PADDING = 12
ANNOUNCEMENT_HEADER_HEIGHT = 48


@dataclass(frozen=True, slots=True)
class AnnouncementHorse:
    """A horse entry for the announcement image."""

    horse_id: str
    name: str
    profile: Image.Image  # 64x64 RGBA


def profile_from_bytes(data: bytes) -> Image.Image:
    """Convert BYTEA image data to a 64x64 RGBA PIL Image."""
    img = Image.open(BytesIO(data))
    img = img.convert("RGBA")
    img = img.resize((PROFILE_SIZE, PROFILE_SIZE), Resampling.NEAREST)
    return img


def render_announcement(
    horses: list[AnnouncementHorse],
    odds: list[float],
    forms: list[str],
    star_ratings: list[str],
    race_number: int,
) -> bytes:
    """Render the pre-race announcement image.

    Args:
        horses: Horse entries with profiles.
        odds: Displayed payout per horse (e.g. 2.2).
        forms: Pre-formatted form strings per horse (e.g. "W-P-L").
        star_ratings: Pre-formatted star strings per horse (e.g. "★★★☆☆").
        race_number: Race number for the header.

    Returns:
        PNG image bytes.
    """
    n = len(horses)
    height = (
        ANNOUNCEMENT_HEADER_HEIGHT + n * ANNOUNCEMENT_ROW_HEIGHT + ANNOUNCEMENT_PADDING
    )
    img = Image.new("RGBA", (CANVAS_WIDTH, height), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img)

    header_font = _load_font(20)
    name_font = _load_font(16)
    detail_font = _load_font(13)
    star_font = _load_font(32)

    # Header
    header_text = f"Race #{race_number}"
    draw.text(
        (CANVAS_WIDTH // 2, ANNOUNCEMENT_PADDING),
        header_text,
        fill=FINISH_COLOR,
        font=header_font,
        anchor="mt",
    )

    # Column headers
    col_y = ANNOUNCEMENT_HEADER_HEIGHT - 16
    draw.text((PROFILE_SIZE + 24, col_y), "Horse", fill=TEXT_COLOR, font=detail_font)
    draw.text((300, col_y), "Odds", fill=TEXT_COLOR, font=detail_font)
    draw.text((380, col_y), "Form", fill=TEXT_COLOR, font=detail_font)
    draw.text((480, col_y), "Rating", fill=TEXT_COLOR, font=detail_font)

    for i, horse in enumerate(horses):
        row_y = ANNOUNCEMENT_HEADER_HEIGHT + i * ANNOUNCEMENT_ROW_HEIGHT

        # Divider line
        if i > 0:
            x_end = CANVAS_WIDTH - ANNOUNCEMENT_PADDING
            draw.line(
                [(ANNOUNCEMENT_PADDING, row_y), (x_end, row_y)],
                fill=LANE_DIVIDER,
                width=1,
            )

        # Profile image
        profile_y = row_y + (ANNOUNCEMENT_ROW_HEIGHT - PROFILE_SIZE) // 2
        img.paste(horse.profile, (ANNOUNCEMENT_PADDING, profile_y), horse.profile)

        # Vertical center of this row
        mid_y = row_y + ANNOUNCEMENT_ROW_HEIGHT // 2

        # Name
        text_x = PROFILE_SIZE + 24
        draw.text(
            (text_x, mid_y),
            horse.name,
            fill=TEXT_COLOR,
            font=name_font,
            anchor="lm",
        )

        # Odds
        draw.text(
            (300, mid_y),
            f"{odds[i]:.1f}:1",
            fill=TEXT_COLOR,
            font=detail_font,
            anchor="lm",
        )

        # Form
        draw.text(
            (380, mid_y),
            forms[i],
            fill=TEXT_COLOR,
            font=detail_font,
            anchor="lm",
        )

        # Star rating
        draw.text(
            (480, mid_y),
            star_ratings[i],
            fill=FINISH_COLOR,
            font=star_font,
            anchor="lm",
        )

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Animated GIF rendering
# ---------------------------------------------------------------------------


def render_race_gif(
    horses: list[RaceHorse],
    result: RaceResult,
    frame_indices: list[int],
    frame_duration_ms: int = 800,
    render_frames: int = 24,
) -> bytes:
    """Render a subset of race frames as an animated GIF.

    Args:
        horses: Horse names and sprites.
        result: Full race simulation result.
        frame_indices: Indices into the sampled frames to include.
        frame_duration_ms: Duration per frame in milliseconds.
        render_frames: Total sampled frames (must match the
            frame_indices range).

    Returns:
        Animated GIF bytes.
    """
    ticks = sample_frames(result.snapshots, render_frames)
    total = len(ticks)

    frames: list[Image.Image] = []
    for idx in frame_indices:
        tick = ticks[idx]
        positions = result.snapshots[tick]
        tick_events = [e for e in result.events if e.tick == tick]
        frame = render_frame(horses, positions, tick_events, tick, idx, total)
        # GIF doesn't support full alpha; convert to RGB with solid background
        frames.append(frame.convert("RGB"))

    if not frames:
        placeholder = Image.new("RGB", (CANVAS_WIDTH, 1), BG_COLOR)
        frames = [placeholder]

    buf = BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=frame_duration_ms,
        loop=0,
    )
    return buf.getvalue()
