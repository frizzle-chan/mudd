"""Race frame renderer.

Pure functions — no database access, no async.
Produces PIL images from race simulation snapshots.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from PIL.Image import Resampling

from mudd.racing.simulation import BurstEvent, RaceResult

_log = logging.getLogger(__name__)

# Font path — UnifontEX monospace installed in the Docker image
_FONT_PATH = "/usr/share/fonts/truetype/unifontex/unifontex.ttf"
_NATIVE_FONT_SIZE = 16


@functools.cache
def _native_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load UnifontEX at its native 16px size, falling back to default."""
    try:
        return ImageFont.truetype(_FONT_PATH, _NATIVE_FONT_SIZE)
    except OSError:
        return ImageFont.load_default()


def _textsize(text: str, scale: int = 1) -> tuple[int, int]:
    """Return (width, height) of *text* at the given integer scale."""
    font = _native_font()
    bbox = font.getbbox(text)
    w = int(bbox[2] - bbox[0])
    h = int(bbox[3] - bbox[1])
    return w * scale, h * scale


def _draw_text(
    img: Image.Image,
    xy: tuple[int, int],
    text: str,
    fill: tuple[int, ...],
    *,
    scale: int = 1,
    anchor: str | None = None,
) -> None:
    """Draw *text* at native 16px, optionally scaled up with nearest-neighbor.

    For ``scale=1`` this is a thin wrapper around ``draw.text()``.
    For ``scale>=2`` the text is rendered to a temporary image at 1x and
    then resized with ``Resampling.NEAREST`` before being pasted onto *img*.
    """
    font = _native_font()
    if scale == 1:
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"
        draw.text(xy, text, fill=fill, font=font, anchor=anchor)
        return

    # Render at 1x to a tight temp image
    bbox = font.getbbox(text)
    w1x = int(bbox[2] - bbox[0])
    h1x = int(bbox[3] - bbox[1])
    tmp = Image.new("RGBA", (w1x, h1x), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    tmp_draw.fontmode = "1"
    tmp_draw.text((-bbox[0], -bbox[1]), text, fill=fill, font=font)

    scaled = tmp.resize((w1x * scale, h1x * scale), Resampling.NEAREST)

    # Resolve anchor to top-left paste coordinates
    sw, sh = scaled.size
    x, y = xy
    if anchor == "lm":
        y = y - sh // 2
    elif anchor == "mt":
        x = x - sw // 2
    img.paste(scaled, (x, y), scaled)


# Layout constants
CANVAS_WIDTH = 640
NAME_MARGIN = 88
TRACK_WIDTH = 530
FINISH_X = 620
FRAME_WIDTH = FINISH_X + 2  # content width for race frames (up to finish line)
LANE_HEIGHT = 24
SPRITE_SIZE = 16
LANE_PADDING = 8
# Mac System 1 window chrome (shared between frames and announcement)
WIN_BORDER_OUTER = 2  # outer border line width
WIN_BORDER_GAP = 1  # gap between outer and inner border
WIN_BORDER_INNER = 1  # inner border line width
WIN_BORDER_TOTAL = 4  # sum of the above
WIN_CHECKER_MARGIN = 12  # checker-filled margin inside window border
WIN_FRAME_INSET = WIN_BORDER_TOTAL + WIN_CHECKER_MARGIN  # total edge-to-content
WIN_TITLEBAR_HEIGHT = 40  # title bar height
WIN_STRIPE_GAP = 3  # vertical pitch of title bar stripes
WIN_TITLE_PAD = 8  # gap between title text and stripes
WIN_STRIPE_MARGIN = 6  # margin from border to stripe start
WIN_SEPARATOR_WIDTH = 1  # horizontal rule width

# Colors
BG_COLOR = (35, 35, 45)
TRACK_BG = (50, 55, 65)
TRACK_BG_ALT = (47, 52, 62)
LANE_DIVIDER = (65, 70, 80)
FINISH_COLOR = (220, 180, 50)
TEXT_COLOR = (200, 200, 210)
MUTED_TEXT_COLOR = (140, 140, 155)
HEADER_TEXT_COLOR = (90, 95, 105)
CHECKER_DARK = BG_COLOR
CHECKER_LIGHT = (50, 52, 62)
ACCENT_COLOR = (180, 150, 50)

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


def _fill_checker(
    img: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
) -> None:
    """Fill a rectangle with a 1px checkerboard pattern."""
    a = bytes(CHECKER_DARK + (255,))
    b = bytes(CHECKER_LIGHT + (255,))
    data = bytearray(w * h * 4)
    for py in range(h):
        for px in range(w):
            off = (py * w + px) * 4
            data[off : off + 4] = a if (px + py) % 2 == 0 else b
    checker = Image.frombytes("RGBA", (w, h), bytes(data))
    img.paste(checker, (x, y))


def _draw_window_border(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
) -> None:
    """Draw Mac System 1 double-line window border."""
    # Outer border
    draw.rectangle(
        [0, 0, width - 1, height - 1],
        outline=LANE_DIVIDER,
        width=WIN_BORDER_OUTER,
    )
    # Inner border (inset by outer + gap)
    inset = WIN_BORDER_OUTER + WIN_BORDER_GAP
    draw.rectangle(
        [inset, inset, width - 1 - inset, height - 1 - inset],
        outline=LANE_DIVIDER,
        width=WIN_BORDER_INNER,
    )


def _draw_titlebar(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    title: str,
    canvas_width: int,
) -> None:
    """Draw a Mac System 1 title bar with centered text and stripes."""
    tb_top = WIN_BORDER_TOTAL
    tb_bottom = tb_top + WIN_TITLEBAR_HEIGHT

    # Title text centered
    tw, th = _textsize(title, scale=2)
    title_x = canvas_width // 2
    title_y = tb_top + (WIN_TITLEBAR_HEIGHT - th) // 2
    _draw_text(img, (title_x, title_y), title, fill=FINISH_COLOR, scale=2, anchor="mt")

    # Stripes: 1px horizontal lines filling title bar on both sides of the title
    stripe_left = WIN_BORDER_TOTAL + WIN_STRIPE_MARGIN
    stripe_right = canvas_width - 1 - WIN_BORDER_TOTAL - WIN_STRIPE_MARGIN
    title_left = title_x - tw // 2 - WIN_TITLE_PAD
    title_right = title_x + tw // 2 + WIN_TITLE_PAD

    all_stripes = list(range(tb_top + WIN_STRIPE_GAP, tb_bottom, WIN_STRIPE_GAP))
    trimmed = all_stripes[2:-3] if len(all_stripes) > 5 else all_stripes
    for y in trimmed:
        if stripe_left < title_left:
            draw.line([(stripe_left, y), (title_left, y)], fill=LANE_DIVIDER, width=1)
        if title_right < stripe_right:
            draw.line([(title_right, y), (stripe_right, y)], fill=LANE_DIVIDER, width=1)

    # Separator below title bar
    sep_y = tb_bottom
    draw.line(
        [(WIN_BORDER_TOTAL, sep_y), (canvas_width - 1 - WIN_BORDER_TOTAL, sep_y)],
        fill=LANE_DIVIDER,
        width=WIN_SEPARATOR_WIDTH,
    )


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
    frame_width = FRAME_WIDTH + WIN_FRAME_INSET * 2
    frame_height = content_h + WIN_FRAME_INSET * 2
    img = Image.new("RGBA", (frame_width, frame_height), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img)
    _draw_window_border(draw, frame_width, frame_height)

    # Checker fill in margin between border and content
    _fill_checker(
        img,
        WIN_BORDER_TOTAL,
        WIN_BORDER_TOTAL,
        frame_width - WIN_BORDER_TOTAL * 2,
        frame_height - WIN_BORDER_TOTAL * 2,
    )

    # Origin offset for content area
    ox, oy = WIN_FRAME_INSET, WIN_FRAME_INSET

    # Content background (covers checker in the content area)
    draw.rectangle(
        [ox, oy, ox + FRAME_WIDTH - 1, oy + content_h - 1],
        fill=BG_COLOR + (255,),
    )

    # Track background (alternating lane stripes, extending into name area)
    track_h = content_h
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
        [(ox + NAME_MARGIN, oy), (ox + NAME_MARGIN, oy + track_h)],
        fill=LANE_DIVIDER,
        width=1,
    )

    # Finish line (2px wide)
    draw.line(
        [(ox + FINISH_X, oy), (ox + FINISH_X, oy + track_h)],
        fill=FINISH_COLOR,
        width=2,
    )

    # Horses
    for i, horse in enumerate(horses):
        lane_y = oy + i * LANE_HEIGHT

        # Name label
        _draw_text(
            img,
            (ox + 4, lane_y + (LANE_HEIGHT - _NATIVE_FONT_SIZE) // 2),
            horse.name[:10],
            fill=TEXT_COLOR,
        )

        # Sprite position: map 0.0-1.0 to NAME_MARGIN+2 .. FINISH_X
        x = (
            ox
            + NAME_MARGIN
            + 2
            + int(positions[i] * (FINISH_X - NAME_MARGIN - 2 - SPRITE_SIZE))
        )
        sprite_y = lane_y + (LANE_HEIGHT - SPRITE_SIZE) // 2
        img.paste(horse.sprite, (x, sprite_y), horse.sprite)

    # Tick label (debug only, bottom-right of content area, low contrast)
    if _log.isEnabledFor(logging.DEBUG):
        tick_text = f"Tick {tick}  ({frame_index + 1}/{total_frames})"
        tw, th = _textsize(tick_text)
        _draw_text(
            img,
            (ox + FRAME_WIDTH - tw - 4, oy + content_h - th - 2),
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

PROFILE_SIZE = 64
ANNOUNCEMENT_ROW_HEIGHT = 80
ANNOUNCEMENT_PADDING = 12
WIN_INFOBAR_HEIGHT = 24  # column header bar height


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
    chrome_top = WIN_BORDER_TOTAL + WIN_TITLEBAR_HEIGHT + WIN_SEPARATOR_WIDTH
    info_top = chrome_top + WIN_INFOBAR_HEIGHT + WIN_SEPARATOR_WIDTH
    height = info_top + n * ANNOUNCEMENT_ROW_HEIGHT + WIN_BORDER_TOTAL
    img = Image.new("RGBA", (CANVAS_WIDTH, height), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img)

    # --- Double border + title bar ---
    _draw_window_border(draw, CANVAS_WIDTH, height)
    _draw_titlebar(img, draw, f"Race #{race_number}", CANVAS_WIDTH)

    # --- Info bar (column headers) ---
    ib_top = chrome_top
    ib_mid_y = ib_top + WIN_INFOBAR_HEIGHT // 2
    _draw_text(
        img, (PROFILE_SIZE + 24, ib_mid_y), "Horse", fill=MUTED_TEXT_COLOR, anchor="lm"
    )
    _draw_text(img, (300, ib_mid_y), "Odds", fill=MUTED_TEXT_COLOR, anchor="lm")
    _draw_text(img, (380, ib_mid_y), "Form", fill=MUTED_TEXT_COLOR, anchor="lm")
    _draw_text(img, (480, ib_mid_y), "Rating", fill=MUTED_TEXT_COLOR, anchor="lm")

    # --- Separator below info bar ---
    sep2_y = ib_top + WIN_INFOBAR_HEIGHT
    draw.line(
        [(WIN_BORDER_TOTAL, sep2_y), (CANVAS_WIDTH - 1 - WIN_BORDER_TOTAL, sep2_y)],
        fill=LANE_DIVIDER,
        width=WIN_SEPARATOR_WIDTH,
    )

    # --- Content rows ---
    content_top = sep2_y + WIN_SEPARATOR_WIDTH

    for i, horse in enumerate(horses):
        row_y = content_top + i * ANNOUNCEMENT_ROW_HEIGHT

        # Divider line between rows
        if i > 0:
            draw.line(
                [
                    (WIN_BORDER_TOTAL, row_y),
                    (CANVAS_WIDTH - 1 - WIN_BORDER_TOTAL, row_y),
                ],
                fill=LANE_DIVIDER,
                width=1,
            )

        # Profile image
        profile_y = row_y + (ANNOUNCEMENT_ROW_HEIGHT - PROFILE_SIZE) // 2
        img.paste(
            horse.profile,
            (WIN_BORDER_TOTAL + ANNOUNCEMENT_PADDING, profile_y),
            horse.profile,
        )

        # Vertical center of this row
        mid_y = row_y + ANNOUNCEMENT_ROW_HEIGHT // 2

        # Name
        text_x = PROFILE_SIZE + 24
        _draw_text(img, (text_x, mid_y), horse.name, fill=TEXT_COLOR, anchor="lm")

        # Odds
        _draw_text(img, (300, mid_y), f"{odds[i]:.1f}:1", fill=TEXT_COLOR, anchor="lm")

        # Form
        _draw_text(img, (380, mid_y), forms[i], fill=TEXT_COLOR, anchor="lm")

        # Star rating
        _draw_text(
            img,
            (480, mid_y),
            star_ratings[i],
            fill=FINISH_COLOR,
            scale=2,
            anchor="lm",
        )

    buf = BytesIO()
    img.save(buf, format="PNG")
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

    # Scale up small images with nearest-neighbor (3x for crisp pixel art)
    while pic.height <= 128:
        pic = pic.resize((pic.width * 3, pic.height * 3), Resampling.NEAREST)

    chrome_top = WIN_BORDER_TOTAL + WIN_TITLEBAR_HEIGHT + WIN_SEPARATOR_WIDTH
    canvas_w = pic.width + WIN_BORDER_TOTAL * 2
    canvas_h = (
        chrome_top
        + pic.height
        + WIN_SEPARATOR_WIDTH
        + WIN_TITLEBAR_HEIGHT
        + WIN_BORDER_TOTAL
    )

    img = Image.new("RGBA", (canvas_w, canvas_h), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img)

    # Border + title bar ("Race #N - WINNER")
    _draw_window_border(draw, canvas_w, canvas_h)
    _draw_titlebar(img, draw, f"Race #{race_number} - WINNER", canvas_w)

    # Victory image
    img.paste(pic, (WIN_BORDER_TOTAL, chrome_top), pic)

    # Separator below image
    sep_y = chrome_top + pic.height
    draw.line(
        [(WIN_BORDER_TOTAL, sep_y), (canvas_w - 1 - WIN_BORDER_TOTAL, sep_y)],
        fill=LANE_DIVIDER,
        width=WIN_SEPARATOR_WIDTH,
    )

    # Name bar — winner name centered (1x to accommodate long names)
    name_top = sep_y + WIN_SEPARATOR_WIDTH
    _, nh = _textsize(winner_name)
    name_y = name_top + (WIN_TITLEBAR_HEIGHT - nh) // 2
    _draw_text(
        img,
        (canvas_w // 2, name_y),
        winner_name,
        fill=TEXT_COLOR,
        anchor="mt",
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
