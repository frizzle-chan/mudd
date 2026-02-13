"""Mac System 1 window chrome renderer.

Shared drawing primitives for window borders, title bars, checker fills,
and text rendering using UnifontEX bitmap font.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont
from PIL.Image import Resampling

# Font path — UnifontEX monospace installed in the Docker image
FONT_PATH = "/usr/share/fonts/truetype/unifontex/unifontex.ttf"
NATIVE_FONT_SIZE = 16


@functools.cache
def native_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load UnifontEX at its native 16px size, falling back to default."""
    try:
        return ImageFont.truetype(FONT_PATH, NATIVE_FONT_SIZE)
    except OSError:
        return ImageFont.load_default()


def textsize(text: str, scale: int = 1) -> tuple[int, int]:
    """Return (width, height) of *text* at the given integer scale."""
    font = native_font()
    bbox = font.getbbox(text)
    w = int(bbox[2] - bbox[0])
    h = int(bbox[3] - bbox[1])
    return w * scale, h * scale


def draw_text(
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
    font = native_font()
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


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

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
LANE_DIVIDER = (65, 70, 80)
FINISH_COLOR = (220, 180, 50)
TEXT_COLOR = (200, 200, 210)
MUTED_TEXT_COLOR = (140, 140, 155)
HEADER_TEXT_COLOR = (90, 95, 105)
CHECKER_DARK = BG_COLOR
CHECKER_LIGHT = (50, 52, 62)


# ---------------------------------------------------------------------------
# Internal drawing helpers
# ---------------------------------------------------------------------------


def vcenter(row_y: int, row_height: int, item_height: int) -> int:
    """Return Y coordinate to vertically center an item in a row."""
    return row_y + (row_height - item_height) // 2


def draw_separator(
    draw: ImageDraw.ImageDraw,
    y: int,
    canvas_width: int,
    *,
    width: int = WIN_SEPARATOR_WIDTH,
) -> None:
    """Draw a horizontal separator line spanning the content area."""
    draw.line(
        [(WIN_BORDER_TOTAL, y), (canvas_width - 1 - WIN_BORDER_TOTAL, y)],
        fill=LANE_DIVIDER,
        width=width,
    )


def fill_checker(
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


def draw_window_border(
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


def draw_titlebar(
    img: Image.Image,
    draw_ctx: ImageDraw.ImageDraw,
    title: str,
    canvas_width: int,
) -> None:
    """Draw a Mac System 1 title bar with centered text and stripes."""
    tb_top = WIN_BORDER_TOTAL
    tb_bottom = tb_top + WIN_TITLEBAR_HEIGHT

    # Title text centered
    tw, th = textsize(title, scale=2)
    title_x = canvas_width // 2
    title_y = vcenter(tb_top, WIN_TITLEBAR_HEIGHT, th)
    draw_text(img, (title_x, title_y), title, fill=FINISH_COLOR, scale=2, anchor="mt")

    # Stripes: 1px horizontal lines filling title bar on both sides of the title
    stripe_left = WIN_BORDER_TOTAL + WIN_STRIPE_MARGIN
    stripe_right = canvas_width - 1 - WIN_BORDER_TOTAL - WIN_STRIPE_MARGIN
    title_left = title_x - tw // 2 - WIN_TITLE_PAD
    title_right = title_x + tw // 2 + WIN_TITLE_PAD

    all_stripes = list(range(tb_top + WIN_STRIPE_GAP, tb_bottom, WIN_STRIPE_GAP))
    trimmed = all_stripes[2:-3] if len(all_stripes) > 5 else all_stripes
    for y in trimmed:
        if stripe_left < title_left:
            draw_ctx.line(
                [(stripe_left, y), (title_left, y)], fill=LANE_DIVIDER, width=1
            )
        if title_right < stripe_right:
            draw_ctx.line(
                [(title_right, y), (stripe_right, y)], fill=LANE_DIVIDER, width=1
            )

    # Separator below title bar
    draw_separator(draw_ctx, tb_bottom, canvas_width)


# ---------------------------------------------------------------------------
# Chrome canvas factory
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChromeCanvas:
    """Canvas with Mac System 1 window chrome already drawn."""

    img: Image.Image
    draw: ImageDraw.ImageDraw
    content_x: int  # left edge of content area
    section_tops: list[int]  # Y of each section's top edge


def chrome_canvas(
    content_width: int,
    section_heights: list[int],
    *,
    title: str | None = None,
    checker: bool = False,
) -> ChromeCanvas:
    """Create a canvas with Mac System 1 window chrome.

    Draws border, optional checker fill, optional titlebar, and separators
    between sections. Returns the canvas with section_tops so callers know
    where to draw content.
    """
    inset = WIN_FRAME_INSET if checker else WIN_BORDER_TOTAL
    canvas_w = content_width + inset * 2

    # Compute section tops and total height
    y = WIN_BORDER_TOTAL + WIN_TITLEBAR_HEIGHT + WIN_SEPARATOR_WIDTH if title else inset

    section_tops: list[int] = []
    for i, h in enumerate(section_heights):
        section_tops.append(y)
        y += h
        if i < len(section_heights) - 1:
            y += WIN_SEPARATOR_WIDTH

    canvas_h = y + (WIN_BORDER_TOTAL if title else inset)

    img = Image.new("RGBA", (canvas_w, canvas_h), BG_COLOR + (255,))
    draw_ctx = ImageDraw.Draw(img)

    draw_window_border(draw_ctx, canvas_w, canvas_h)

    if checker:
        fill_checker(
            img,
            WIN_BORDER_TOTAL,
            WIN_BORDER_TOTAL,
            canvas_w - WIN_BORDER_TOTAL * 2,
            canvas_h - WIN_BORDER_TOTAL * 2,
        )

    if title:
        draw_titlebar(img, draw_ctx, title, canvas_w)

    # Separators between sections
    for i in range(len(section_heights) - 1):
        sep_y = section_tops[i] + section_heights[i]
        draw_separator(draw_ctx, sep_y, canvas_w)

    return ChromeCanvas(
        img=img,
        draw=draw_ctx,
        content_x=inset,
        section_tops=section_tops,
    )
