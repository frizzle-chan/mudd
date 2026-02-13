"""Map image renderer.

Pure functions — no database access, no async.
Composites pre-drawn PNG layers (base + per-room overlays) to render
a progressive map. Falls back to a static "map offline" image when
no layers directory is available.
"""

from __future__ import annotations

import functools
from io import BytesIO
from pathlib import Path

from PIL import Image

from mudd.rendering.chrome import (
    MUTED_TEXT_COLOR,
    chrome_canvas,
    draw_text,
    textsize,
)

# Default layers directory for the mansion world
_DEFAULT_LAYERS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "worlds" / "mansion_map"
)


# ---------------------------------------------------------------------------
# Layered rendering
# ---------------------------------------------------------------------------


@functools.cache
def _load_layer(path: Path) -> Image.Image:
    """Load and cache a PNG layer. Static files, cache invalidated on restart."""
    return Image.open(path).convert("RGBA")


def _render_layered(
    layers_dir: Path,
    visited_room_ids: set[str],
) -> bytes:
    """Composite room layers onto the base image.

    1. Start with base.png
    2. Alpha-composite each visited room's layer
    """
    base = _load_layer(layers_dir / "base.png")
    result = base.copy()

    for room_id in sorted(visited_room_ids):
        layer_path = layers_dir / f"{room_id}.png"
        if not layer_path.is_file():
            continue
        layer = _load_layer(layer_path)
        result = Image.alpha_composite(result, layer)

    # Wrap in chrome
    cc = chrome_canvas(result.width, [result.height], title="MAP")
    cc.img.paste(result, (cc.content_x, cc.section_tops[0]), result)

    buf = BytesIO()
    cc.img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Offline fallback
# ---------------------------------------------------------------------------


def _render_offline() -> bytes:
    """Render a small static image that says 'map offline'."""
    text = "map offline"
    tw, th = textsize(text)
    content_w = max(tw + 32, 320)
    content_h = max(th + 32, 48)

    cc = chrome_canvas(content_w, [content_h], title="MAP")

    # Center text in content area
    x = cc.content_x + (content_w - tw) // 2
    y = cc.section_tops[0] + (content_h - th) // 2
    draw_text(cc.img, (x, y), text, fill=MUTED_TEXT_COLOR)

    buf = BytesIO()
    cc.img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_map_image(
    visited_room_ids: set[str],
    *,
    layers_dir: Path = _DEFAULT_LAYERS_DIR,
) -> bytes:
    """Generate a map image showing visited rooms.

    If a ``base.png`` exists in *layers_dir*, uses layer-based compositing
    (pre-drawn PNG overlays per room). Otherwise returns a static
    "map offline" placeholder.

    Args:
        visited_room_ids: Room IDs the user has visited.
        layers_dir: Directory containing ``base.png`` and per-room PNGs.

    Returns:
        PNG image bytes.
    """
    if (layers_dir / "base.png").is_file():
        return _render_layered(layers_dir, visited_room_ids)
    return _render_offline()
