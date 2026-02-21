"""Race frame renderer.

Pure functions — no database access, no async.
Produces PIL images from race simulation snapshots.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw
from PIL.Image import Resampling

from mudd.racing.simulation import BurstEvent, RaceResult
from mudd.rendering.chrome import (
    BG_COLOR,
    FINISH_COLOR,
    HEADER_TEXT_COLOR,
    LANE_DIVIDER,
    MUTED_TEXT_COLOR,
    NATIVE_FONT_SIZE,
    TEXT_COLOR,
    WIN_BORDER_TOTAL,
    WIN_TITLEBAR_HEIGHT,
    chrome_canvas,
    draw_separator,
    draw_text,
    textsize,
    vcenter,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

CANVAS_WIDTH = 640
NAME_MARGIN = 88
TRACK_WIDTH = 530
FINISH_X = 620
FRAME_WIDTH = FINISH_X + 2  # content width for race frames (up to finish line)
LANE_HEIGHT = 24
SPRITE_SIZE = 16

# Race frame layout
NAME_TEXT_PAD = 4
NAME_TRUNCATE = 10
TRACK_START_PAD = 2
FINISH_LINE_WIDTH = 2

# Announcement layout
PROFILE_SIZE = 64
ANNOUNCEMENT_ROW_HEIGHT = 80
ANNOUNCEMENT_PADDING = 12
WIN_INFOBAR_HEIGHT = 24  # column header bar height
ANN_NAME_X = PROFILE_SIZE + 24
ANN_ODDS_X = 300
ANN_FORM_X = 380
ANN_RATING_X = 480

# Victory upscaling
VICTORY_UPSCALE_THRESHOLD = 128
VICTORY_UPSCALE_FACTOR = 3

# Colors (racing-specific)
TRACK_BG = (50, 55, 65)
TRACK_BG_ALT = (47, 52, 62)

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


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RaceHorse:
    """A horse with a name and sprite for rendering."""

    name: str
    sprite: Image.Image  # 16x16 RGBA


@dataclass(frozen=True, slots=True)
class AnnouncementHorse:
    """A horse entry for the announcement image."""

    horse_id: str
    name: str
    profile: Image.Image  # 64x64 RGBA


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


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


def profile_from_bytes(data: bytes) -> Image.Image:
    """Convert BYTEA image data to a 64x64 RGBA PIL Image."""
    img = Image.open(BytesIO(data))
    img = img.convert("RGBA")
    img = img.resize((PROFILE_SIZE, PROFILE_SIZE), Resampling.NEAREST)
    return img


# ---------------------------------------------------------------------------
# Race frame rendering
# ---------------------------------------------------------------------------


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
    content_h = n * LANE_HEIGHT
    cc = chrome_canvas(FRAME_WIDTH, [content_h], checker=True)
    img, draw = cc.img, cc.draw
    ox = cc.content_x
    oy = cc.section_tops[0]

    # --- Background ---

    # Content background (covers checker in the content area)
    draw.rectangle(
        [ox, oy, ox + FRAME_WIDTH - 1, oy + content_h - 1],
        fill=BG_COLOR + (255,),
    )

    # Track background (alternating lane stripes, extending into name area)
    for i in range(n):
        lane_y = oy + i * LANE_HEIGHT
        fill = TRACK_BG if i % 2 == 0 else TRACK_BG_ALT
        draw.rectangle(
            [
                ox,
                lane_y,
                ox + NAME_MARGIN + TRACK_WIDTH,
                lane_y + LANE_HEIGHT,
            ],
            fill=fill,
        )

    # --- Cross-cutting lines ---

    # Lane dividers
    for i in range(1, n):
        y = oy + i * LANE_HEIGHT
        draw.line(
            [(ox, y), (ox + NAME_MARGIN + TRACK_WIDTH, y)],
            fill=LANE_DIVIDER,
            width=1,
        )

    # Name/track border
    draw.line(
        [(ox + NAME_MARGIN, oy), (ox + NAME_MARGIN, oy + content_h)],
        fill=LANE_DIVIDER,
        width=1,
    )

    # Finish line
    draw.line(
        [(ox + FINISH_X, oy), (ox + FINISH_X, oy + content_h)],
        fill=FINISH_COLOR,
        width=FINISH_LINE_WIDTH,
    )

    # --- Per-lane content ---

    for i, horse in enumerate(horses):
        lane_y = oy + i * LANE_HEIGHT

        # Name label
        draw_text(
            img,
            (ox + NAME_TEXT_PAD, vcenter(lane_y, LANE_HEIGHT, NATIVE_FONT_SIZE)),
            horse.name[:NAME_TRUNCATE],
            fill=TEXT_COLOR,
        )

        # Sprite position: map 0.0-1.0 to NAME_MARGIN+TRACK_START_PAD .. FINISH_X
        x = (
            ox
            + NAME_MARGIN
            + TRACK_START_PAD
            + int(
                positions[i] * (FINISH_X - NAME_MARGIN - TRACK_START_PAD - SPRITE_SIZE)
            )
        )
        sprite_y = vcenter(lane_y, LANE_HEIGHT, SPRITE_SIZE)
        img.paste(horse.sprite, (x, sprite_y), horse.sprite)

    # Tick label (debug only, bottom-right of content area, low contrast)
    if _log.isEnabledFor(logging.DEBUG):
        tick_text = f"Tick {tick}  ({frame_index + 1}/{total_frames})"
        tw, th = textsize(tick_text)
        draw_text(
            img,
            (ox + FRAME_WIDTH - tw - NAME_TEXT_PAD, oy + content_h - th - 2),
            tick_text,
            fill=HEADER_TEXT_COLOR,
        )

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


def _draw_announcement_row(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    canvas_width: int,
    row_y: int,
    horse: AnnouncementHorse,
    odd: float,
    form: str,
    star_rating: str,
    *,
    divider: bool = False,
) -> None:
    """Draw one row of the announcement table."""
    if divider:
        draw_separator(draw, row_y, canvas_width)

    # Profile image
    profile_y = vcenter(row_y, ANNOUNCEMENT_ROW_HEIGHT, PROFILE_SIZE)
    img.paste(
        horse.profile,
        (WIN_BORDER_TOTAL + ANNOUNCEMENT_PADDING, profile_y),
        horse.profile,
    )

    # Text columns (vertically centered)
    mid_y = row_y + ANNOUNCEMENT_ROW_HEIGHT // 2
    draw_text(img, (ANN_NAME_X, mid_y), horse.name, fill=TEXT_COLOR, anchor="lm")
    draw_text(img, (ANN_ODDS_X, mid_y), f"{odd:.1f}:1", fill=TEXT_COLOR, anchor="lm")
    draw_text(img, (ANN_FORM_X, mid_y), form, fill=TEXT_COLOR, anchor="lm")
    draw_text(
        img,
        (ANN_RATING_X, mid_y),
        star_rating,
        fill=FINISH_COLOR,
        scale=2,
        anchor="lm",
    )


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
    cc = chrome_canvas(
        CANVAS_WIDTH - WIN_BORDER_TOTAL * 2,
        [WIN_INFOBAR_HEIGHT, n * ANNOUNCEMENT_ROW_HEIGHT],
        title=f"Race #{race_number}",
    )

    # Info bar (column headers)
    ib_mid_y = cc.section_tops[0] + WIN_INFOBAR_HEIGHT // 2
    draw_text(
        cc.img, (ANN_NAME_X, ib_mid_y), "Horse", fill=MUTED_TEXT_COLOR, anchor="lm"
    )
    draw_text(
        cc.img, (ANN_ODDS_X, ib_mid_y), "Odds", fill=MUTED_TEXT_COLOR, anchor="lm"
    )
    draw_text(
        cc.img, (ANN_FORM_X, ib_mid_y), "Form", fill=MUTED_TEXT_COLOR, anchor="lm"
    )
    draw_text(
        cc.img, (ANN_RATING_X, ib_mid_y), "Rating", fill=MUTED_TEXT_COLOR, anchor="lm"
    )

    # Content rows
    content_top = cc.section_tops[1]
    for i, horse in enumerate(horses):
        row_y = content_top + i * ANNOUNCEMENT_ROW_HEIGHT
        _draw_announcement_row(
            cc.img,
            cc.draw,
            cc.img.width,
            row_y,
            horse,
            odds[i],
            forms[i],
            star_ratings[i],
            divider=i > 0,
        )

    buf = BytesIO()
    cc.img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Winner image
# ---------------------------------------------------------------------------


def render_winner(
    victory_image: bytes,
    winner_name: str,
    race_number: int,
) -> bytes:
    """Wrap a victory image in Mac System 1 window chrome.

    Args:
        victory_image: Raw image bytes (PNG/JPEG/etc).
        winner_name: The winning horse's name.
        race_number: Race number for the title bar.

    Returns:
        PNG image bytes.
    """
    pic = Image.open(BytesIO(victory_image)).convert("RGBA")

    # Scale up small images with nearest-neighbor (crisp pixel art)
    while pic.height <= VICTORY_UPSCALE_THRESHOLD:
        pic = pic.resize(
            (pic.width * VICTORY_UPSCALE_FACTOR, pic.height * VICTORY_UPSCALE_FACTOR),
            Resampling.NEAREST,
        )

    cc = chrome_canvas(
        pic.width,
        [pic.height, WIN_TITLEBAR_HEIGHT],
        title=f"Race #{race_number} - WINNER",
    )

    # Victory image
    cc.img.paste(pic, (cc.content_x, cc.section_tops[0]), pic)

    # Name bar — winner name centered (1x to accommodate long names)
    _, nh = textsize(winner_name)
    name_y = vcenter(cc.section_tops[1], WIN_TITLEBAR_HEIGHT, nh)
    draw_text(
        cc.img,
        (cc.img.width // 2, name_y),
        winner_name,
        fill=TEXT_COLOR,
        anchor="mt",
    )

    buf = BytesIO()
    cc.img.save(buf, format="PNG")
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
