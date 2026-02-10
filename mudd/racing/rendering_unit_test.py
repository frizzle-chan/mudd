"""Unit tests for mudd.racing.rendering — structural properties only."""

from __future__ import annotations

from PIL import Image

from mudd.racing.rendering import (
    CANVAS_WIDTH,
    FRAME_WIDTH,
    LANE_HEIGHT,
    SPRITE_SIZE,
    WIN_BORDER_TOTAL,
    WIN_FRAME_INSET,
    WIN_INFOBAR_HEIGHT,
    WIN_SEPARATOR_WIDTH,
    WIN_TITLEBAR_HEIGHT,
    RaceHorse,
    _chrome_canvas,
    _vcenter,
    fallback_sprite,
    render_frame,
    render_race,
    sample_frames,
    sprite_from_bytes,
    tile_frames,
)
from mudd.racing.simulation import RaceResult


def _make_sprite() -> Image.Image:
    return Image.new("RGBA", (SPRITE_SIZE, SPRITE_SIZE), (255, 0, 0, 255))


def _make_horses(n: int) -> list[RaceHorse]:
    return [RaceHorse(name=f"Horse{i}", sprite=_make_sprite()) for i in range(n)]


def _make_result(n_horses: int, n_ticks: int = 60) -> RaceResult:
    """Build a minimal RaceResult with linear progress."""
    snapshots: list[list[float]] = []
    for t in range(n_ticks + 1):
        frac = t / n_ticks
        snapshots.append([frac * (1 - i * 0.05) for i in range(n_horses)])
    return RaceResult(
        snapshots=snapshots,
        events=[],
        finishing_order=list(range(n_horses)),
        horse_ids=[f"horse_{i}" for i in range(n_horses)],
    )


class TestVcenter:
    def test_centers_item_in_row(self) -> None:
        assert _vcenter(10, 100, 20) == 50

    def test_integer_division_rounds_down(self) -> None:
        # (11 - 4) // 2 = 3
        assert _vcenter(0, 11, 4) == 3

    def test_zero_offset(self) -> None:
        assert _vcenter(0, 24, 16) == 4

    def test_item_equals_row(self) -> None:
        assert _vcenter(5, 20, 20) == 5


class TestChromeCanvasChecker:
    def test_dimensions_single_section(self) -> None:
        cc = _chrome_canvas(100, [50], checker=True)
        assert cc.img.size == (100 + WIN_FRAME_INSET * 2, 50 + WIN_FRAME_INSET * 2)
        assert cc.content_x == WIN_FRAME_INSET
        assert cc.section_tops == [WIN_FRAME_INSET]

    def test_mode_is_rgba(self) -> None:
        cc = _chrome_canvas(100, [50], checker=True)
        assert cc.img.mode == "RGBA"


class TestChromeCanvasTitled:
    def test_dimensions_single_section(self) -> None:
        cc = _chrome_canvas(100, [50], title="Test")
        expected_h = (
            WIN_BORDER_TOTAL
            + WIN_TITLEBAR_HEIGHT
            + WIN_SEPARATOR_WIDTH
            + 50
            + WIN_BORDER_TOTAL
        )
        assert cc.img.size == (100 + WIN_BORDER_TOTAL * 2, expected_h)
        assert cc.content_x == WIN_BORDER_TOTAL
        assert cc.section_tops == [
            WIN_BORDER_TOTAL + WIN_TITLEBAR_HEIGHT + WIN_SEPARATOR_WIDTH
        ]

    def test_dimensions_multi_section(self) -> None:
        cc = _chrome_canvas(100, [24, 80], title="Test")
        expected_h = (
            WIN_BORDER_TOTAL
            + WIN_TITLEBAR_HEIGHT
            + WIN_SEPARATOR_WIDTH
            + 24
            + WIN_SEPARATOR_WIDTH
            + 80
            + WIN_BORDER_TOTAL
        )
        assert cc.img.size == (100 + WIN_BORDER_TOTAL * 2, expected_h)
        chrome_top = WIN_BORDER_TOTAL + WIN_TITLEBAR_HEIGHT + WIN_SEPARATOR_WIDTH
        assert cc.section_tops == [chrome_top, chrome_top + 24 + WIN_SEPARATOR_WIDTH]

    def test_announcement_dimensions(self) -> None:
        """Verify _chrome_canvas matches render_announcement's old manual layout."""
        n = 3
        cc = _chrome_canvas(
            CANVAS_WIDTH - WIN_BORDER_TOTAL * 2,
            [WIN_INFOBAR_HEIGHT, n * 80],
            title="Race #1",
        )
        assert cc.img.width == CANVAS_WIDTH
        # Old formula: info_top + n * ROW_HEIGHT + WIN_BORDER_TOTAL
        chrome_top = WIN_BORDER_TOTAL + WIN_TITLEBAR_HEIGHT + WIN_SEPARATOR_WIDTH
        info_top = chrome_top + WIN_INFOBAR_HEIGHT + WIN_SEPARATOR_WIDTH
        expected_h = info_top + n * 80 + WIN_BORDER_TOTAL
        assert cc.img.height == expected_h


class TestSampleFrames:
    def test_default_returns_13_indices(self) -> None:
        snapshots = [[0.0]] * 61  # ticks 0..60
        result = sample_frames(snapshots)
        assert len(result) == 13

    def test_first_and_last(self) -> None:
        snapshots = [[0.0]] * 61
        result = sample_frames(snapshots)
        assert result[0] == 0
        assert result[-1] == 60

    def test_custom_render_frames(self) -> None:
        snapshots = [[0.0]] * 61
        result = sample_frames(snapshots, render_frames=6)
        assert len(result) == 7
        assert result[0] == 0
        assert result[-1] == 60

    def test_single_snapshot(self) -> None:
        result = sample_frames([[0.0]])
        assert result == [0]


class TestSpriteFromBytes:
    def test_returns_correct_size_and_mode(self) -> None:
        img = Image.new("RGB", (32, 32), (100, 100, 100))
        from io import BytesIO

        buf = BytesIO()
        img.save(buf, format="PNG")
        result = sprite_from_bytes(buf.getvalue())
        assert result.size == (SPRITE_SIZE, SPRITE_SIZE)
        assert result.mode == "RGBA"


class TestFallbackSprite:
    def test_returns_correct_size_and_mode(self) -> None:
        sprite = fallback_sprite(0)
        assert sprite.size == (SPRITE_SIZE, SPRITE_SIZE)
        assert sprite.mode == "RGBA"

    def test_different_indices_different_colors(self) -> None:
        s0 = fallback_sprite(0)
        s1 = fallback_sprite(1)
        # Different colors -> different pixel data
        assert list(s0.get_flattened_data()) != list(s1.get_flattened_data())

    def test_wraps_around_palette(self) -> None:
        # Should not raise for large indices
        sprite = fallback_sprite(100)
        assert sprite.size == (SPRITE_SIZE, SPRITE_SIZE)


class TestRenderFrame:
    def test_dimensions(self) -> None:
        horses = _make_horses(4)
        positions = [0.0, 0.25, 0.5, 1.0]
        frame = render_frame(
            horses, positions, [], tick=10, frame_index=0, total_frames=13
        )
        assert frame.width == FRAME_WIDTH + WIN_FRAME_INSET * 2
        assert frame.height == 4 * LANE_HEIGHT + WIN_FRAME_INSET * 2
        assert frame.mode == "RGBA"

    def test_single_horse(self) -> None:
        horses = _make_horses(1)
        frame = render_frame(horses, [0.5], [], tick=0, frame_index=0, total_frames=1)
        assert frame.height == LANE_HEIGHT + WIN_FRAME_INSET * 2


class TestRenderRace:
    def test_returns_correct_frame_count(self) -> None:
        horses = _make_horses(3)
        result = _make_result(3)
        frames = render_race(horses, result)
        assert len(frames) == 13

    def test_custom_render_frames(self) -> None:
        horses = _make_horses(3)
        result = _make_result(3)
        frames = render_race(horses, result, render_frames=6)
        assert len(frames) == 7

    def test_all_frames_same_width(self) -> None:
        horses = _make_horses(5)
        result = _make_result(5)
        frames = render_race(horses, result)
        widths = {f.width for f in frames}
        assert widths == {FRAME_WIDTH + WIN_FRAME_INSET * 2}


class TestTileFrames:
    def test_total_height(self) -> None:
        horses = _make_horses(3)
        result = _make_result(3)
        frames = render_race(horses, result)
        gap = 4
        tiled = tile_frames(frames, gap=gap)
        expected_height = sum(f.height for f in frames) + gap * (len(frames) - 1)
        assert tiled.width == FRAME_WIDTH + WIN_FRAME_INSET * 2
        assert tiled.height == expected_height

    def test_empty_frames(self) -> None:
        tiled = tile_frames([])
        assert tiled.width == CANVAS_WIDTH
        assert tiled.height == 1

    def test_mode_is_rgba(self) -> None:
        horses = _make_horses(2)
        result = _make_result(2)
        frames = render_race(horses, result)
        tiled = tile_frames(frames)
        assert tiled.mode == "RGBA"
