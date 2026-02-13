"""Map image renderer.

Pure functions — no database access, no async.
Produces a placeholder map image showing visited/unvisited rooms grouped by zone.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from PIL.Image import Resampling

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
) -> None:
    """Draw *text* at native 16px, optionally scaled up with nearest-neighbor."""
    font = _native_font()
    if scale == 1:
        draw = ImageDraw.Draw(img)
        draw.fontmode = "1"
        draw.text(xy, text, fill=fill, font=font)
        return

    bbox = font.getbbox(text)
    w1x = int(bbox[2] - bbox[0])
    h1x = int(bbox[3] - bbox[1])
    tmp = Image.new("RGBA", (w1x, h1x), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    tmp_draw.fontmode = "1"
    tmp_draw.text((-bbox[0], -bbox[1]), text, fill=fill, font=font)

    scaled = tmp.resize((w1x * scale, h1x * scale), Resampling.NEAREST)
    img.paste(scaled, xy, scaled)


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

PADDING = 12
ROOM_WIDTH = 120
ROOM_HEIGHT = 28
ROOM_GAP_X = 8
ROOM_GAP_Y = 6
ZONE_HEADER_HEIGHT = 24
ZONE_GAP = 16
ROOMS_PER_ROW = 4

# Colors
BG_COLOR = (35, 35, 45)
ROOM_VISITED = (60, 120, 80)
ROOM_CURRENT = (80, 160, 220)
ROOM_FOGGED = (50, 50, 60)
TEXT_COLOR = (200, 200, 210)
FOGGED_TEXT_COLOR = (90, 90, 100)
ZONE_TEXT_COLOR = (180, 160, 100)
BORDER_COLOR = (70, 75, 85)
CURRENT_BORDER_COLOR = (100, 180, 240)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MapRoom:
    """A room for map rendering."""

    id: str
    name: str
    zone_id: str


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def generate_map_image(
    all_rooms: list[MapRoom],
    visited_room_ids: set[str],
    current_room_id: str | None,
) -> bytes:
    """Generate a placeholder map image.

    Rooms are grouped by zone. Visited rooms are shown in green,
    the current room in blue, and unvisited rooms are fogged out.

    Args:
        all_rooms: All rooms in the game world.
        visited_room_ids: Room IDs the user has visited.
        current_room_id: The user's current room ID (highlighted).

    Returns:
        PNG image bytes.
    """
    # Group rooms by zone
    zones: dict[str, list[MapRoom]] = {}
    for room in all_rooms:
        zones.setdefault(room.zone_id, []).append(room)

    # Calculate canvas dimensions
    zone_ids = sorted(zones.keys())
    total_height = PADDING
    canvas_width = (
        PADDING * 2 + ROOMS_PER_ROW * ROOM_WIDTH + (ROOMS_PER_ROW - 1) * ROOM_GAP_X
    )

    zone_layouts: list[tuple[str, list[MapRoom], int]] = []
    for zone_id in zone_ids:
        rooms = zones[zone_id]
        rows = (len(rooms) + ROOMS_PER_ROW - 1) // ROOMS_PER_ROW
        zone_height = ZONE_HEADER_HEIGHT + rows * ROOM_HEIGHT + (rows - 1) * ROOM_GAP_Y
        zone_layouts.append((zone_id, rooms, total_height))
        total_height += zone_height + ZONE_GAP

    total_height += PADDING - ZONE_GAP  # remove trailing gap, add bottom padding

    # Ensure minimum dimensions
    total_height = max(total_height, 64)
    canvas_width = max(canvas_width, 200)

    img = Image.new("RGBA", (canvas_width, total_height), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img)

    for zone_id, rooms, y_offset in zone_layouts:
        # Zone header
        _draw_text(img, (PADDING, y_offset), zone_id.upper(), fill=ZONE_TEXT_COLOR)

        # Rooms
        for i, room in enumerate(rooms):
            col = i % ROOMS_PER_ROW
            row = i // ROOMS_PER_ROW
            x = PADDING + col * (ROOM_WIDTH + ROOM_GAP_X)
            y = y_offset + ZONE_HEADER_HEIGHT + row * (ROOM_HEIGHT + ROOM_GAP_Y)

            is_current = room.id == current_room_id
            is_visited = room.id in visited_room_ids

            if is_current:
                bg = ROOM_CURRENT
                border = CURRENT_BORDER_COLOR
                text_color = TEXT_COLOR
            elif is_visited:
                bg = ROOM_VISITED
                border = BORDER_COLOR
                text_color = TEXT_COLOR
            else:
                bg = ROOM_FOGGED
                border = BORDER_COLOR
                text_color = FOGGED_TEXT_COLOR

            draw.rectangle(
                [x, y, x + ROOM_WIDTH - 1, y + ROOM_HEIGHT - 1],
                fill=bg,
                outline=border,
            )

            # Truncate room name to fit
            label = room.name if len(room.name) <= 12 else room.name[:11] + "\u2026"
            if not is_visited and not is_current:
                label = "???"
            _draw_text(
                img,
                (x + 4, y + (ROOM_HEIGHT - _NATIVE_FONT_SIZE) // 2),
                label,
                fill=text_color,
            )

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
