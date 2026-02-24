"""Image regression tests for mudd.rendering.chrome.

Uses pytest-regressions to compare rendered chrome against checked-in
baseline PNGs. Regenerate baselines with ``pytest --regen-all``.
"""

from __future__ import annotations

from io import BytesIO

from pytest_regressions.image_regression import ImageRegressionFixture

from mudd.rendering.chrome import (
    MUTED_TEXT_COLOR,
    chrome_canvas,
    draw_text,
    textsize,
)


def test_checker_chrome(image_regression: ImageRegressionFixture) -> None:
    """Plain chrome with checker fill, no title."""
    cc = chrome_canvas(200, [80], checker=True)
    buf = BytesIO()
    cc.img.save(buf, format="PNG")
    image_regression.check(buf.getvalue())


def test_titled_single_section(image_regression: ImageRegressionFixture) -> None:
    """Titled chrome with a single content section."""
    cc = chrome_canvas(200, [80], title="Test")
    buf = BytesIO()
    cc.img.save(buf, format="PNG")
    image_regression.check(buf.getvalue())


def test_titled_multi_section(image_regression: ImageRegressionFixture) -> None:
    """Titled chrome with multiple content sections separated by rules."""
    cc = chrome_canvas(200, [24, 80], title="Test")
    buf = BytesIO()
    cc.img.save(buf, format="PNG")
    image_regression.check(buf.getvalue())


def test_titled_with_text(image_regression: ImageRegressionFixture) -> None:
    """Titled chrome with text drawn into the content area."""
    text = "hello world"
    tw, th = textsize(text)
    cc = chrome_canvas(max(tw + 32, 200), [max(th + 16, 40)], title="Demo")
    x = cc.content_x + 8
    y = cc.section_tops[0] + 8
    draw_text(cc.img, (x, y), text, fill=MUTED_TEXT_COLOR)
    buf = BytesIO()
    cc.img.save(buf, format="PNG")
    image_regression.check(buf.getvalue())
