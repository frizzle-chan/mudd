# mudd/racing

Pure rendering functions for race images (frames, announcements, GIFs). No database access, no async.

## Font rendering

UnifontEX is a **bitmap font with native glyphs at 16px**. Loading it at any other size causes FreeType to interpolate the bitmaps, producing blurry text.

Rules:
- Always render text via `_draw_text()`, which uses the font at its native 16px size.
- For larger text, pass `scale=2` (or higher integer) to `_draw_text()` — it renders at 1x then scales up with `Resampling.NEAREST` for crisp results.
- Never call `ImageFont.truetype` directly or pass arbitrary pixel sizes.
- Use `_textsize()` to measure text dimensions at a given scale.

## Visual check

After changing rendering code, run `just race` and inspect the images in `.tasks/race/` (announcement.png, race frames, photo_finish.png) to verify text is crisp and layout is correct.
