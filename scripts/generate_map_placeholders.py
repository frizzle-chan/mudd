#!/usr/bin/env python3
"""Generate placeholder map layer PNGs for the mansion world.

Produces a base.png and one {room_id}.png per room in data/worlds/mansion_map/.
Canvas size: 640x480.

Usage:
    python scripts/generate_map_placeholders.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CANVAS_W = 640
CANVAS_H = 480
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "worlds" / "mansion_map"

# Font for room labels
_FONT_PATH = "/usr/share/fonts/truetype/unifontex/unifontex.ttf"
_FONT_SIZE = 14

# Layout: room_id -> (x, y, w, h)
# 5 columns x 3 rows grid with padding
_COL_W = 120
_ROW_H = 140
_PAD_X = 10
_PAD_Y = 10
_GAP_X = 6
_GAP_Y = 10


def _grid(col: int, row: int) -> tuple[int, int, int, int]:
    x = _PAD_X + col * (_COL_W + _GAP_X)
    y = _PAD_Y + row * (_ROW_H + _GAP_Y)
    return (x, y, _COL_W, _ROW_H)


ROOM_LAYOUT: dict[str, tuple[int, int, int, int]] = {
    "foyer": _grid(0, 0),
    "sitting-room": _grid(1, 0),
    "hallway": _grid(2, 0),
    "restroom": _grid(3, 0),
    "office": _grid(4, 0),
    "gallery": _grid(0, 1),
    "library": _grid(1, 1),
    "screening-room": _grid(2, 1),
    "banquet-hall": _grid(3, 1),
    "kitchen": _grid(4, 1),
    "freezer": _grid(0, 2),
    "store-room": _grid(1, 2),
    "lounge": _grid(2, 2),
    "courtyard": _grid(3, 2),
    "race-track": _grid(4, 2),
}

# Room fill colors (muted tones)
ROOM_COLORS: dict[str, tuple[int, int, int]] = {
    "foyer": (100, 130, 90),
    "sitting-room": (130, 100, 90),
    "hallway": (110, 110, 120),
    "restroom": (90, 120, 130),
    "office": (130, 120, 80),
    "gallery": (120, 90, 120),
    "library": (100, 90, 130),
    "screening-room": (80, 100, 120),
    "banquet-hall": (130, 110, 90),
    "kitchen": (120, 130, 90),
    "freezer": (80, 110, 130),
    "store-room": (110, 100, 90),
    "lounge": (120, 100, 110),
    "courtyard": (90, 130, 100),
    "race-track": (130, 120, 100),
}

# Base layer outline color (faint)
OUTLINE_COLOR = (55, 55, 65)
BASE_BG = (35, 35, 45)
LABEL_COLOR = (200, 200, 210)


def _load_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(_FONT_PATH, _FONT_SIZE)
    except OSError:
        return ImageFont.load_default()


def generate_base(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> None:
    """Generate base.png — dark background with faint room outlines."""
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BASE_BG + (255,))
    draw = ImageDraw.Draw(img)

    for room_id, (x, y, w, h) in ROOM_LAYOUT.items():
        draw.rectangle([x, y, x + w - 1, y + h - 1], outline=OUTLINE_COLOR)
        # Faint room label
        label = room_id.replace("-", " ").title()
        if len(label) > 14:
            label = label[:13] + "\u2026"
        bbox = font.getbbox(label)
        tw = bbox[2] - bbox[0]
        tx = x + (w - tw) // 2
        ty = y + h // 2 - _FONT_SIZE // 2
        draw.text((tx, ty), label, fill=(70, 70, 80), font=font)

    img.save(OUTPUT_DIR / "base.png", format="PNG")
    print(f"  base.png ({CANVAS_W}x{CANVAS_H})")


def generate_room_layer(
    room_id: str,
    region: tuple[int, int, int, int],
    color: tuple[int, int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """Generate a transparent PNG with only the given room's region filled."""
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    x, y, w, h = region
    draw.rectangle([x, y, x + w - 1, y + h - 1], fill=color + (255,))

    # Room label centered in the region
    label = room_id.replace("-", " ").title()
    if len(label) > 14:
        label = label[:13] + "\u2026"
    bbox = font.getbbox(label)
    tw = bbox[2] - bbox[0]
    tx = x + (w - tw) // 2
    ty = y + h // 2 - _FONT_SIZE // 2
    draw.text((tx, ty), label, fill=LABEL_COLOR, font=font)

    img.save(OUTPUT_DIR / f"{room_id}.png", format="PNG")
    print(f"  {room_id}.png")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    font = _load_font()

    print("Generating placeholder map layers:")
    generate_base(font)

    for room_id, region in ROOM_LAYOUT.items():
        color = ROOM_COLORS[room_id]
        generate_room_layer(room_id, region, color, font)

    print(f"\nDone — {1 + len(ROOM_LAYOUT)} files in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
