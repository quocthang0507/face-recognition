"""Responsive layout checks."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

OVERFLOWING = """() => {
  const width = document.documentElement.clientWidth;
  const outside = [...document.querySelectorAll('body *')].filter((element) => {
    if (element.closest('.table-wrap') || element.closest('.modal')) return false;
    const box = element.getBoundingClientRect();
    return box.width > 0 && box.right > width + 1;
  }).map((element) => element.tagName + '.' + element.className);
  return {scroll: document.documentElement.scrollWidth, width, outside};
}"""


@pytest.mark.parametrize("mode", ["desk", "tv"])
@pytest.mark.parametrize("width", [1440, 768, 375])
def test_page_has_no_horizontal_overflow(dashboard, width: int, mode: str) -> None:
    dashboard.click(f"#display-{mode}")

    dashboard.set_viewport_size({"width": width, "height": 900})

    result = dashboard.evaluate(OVERFLOWING)
    assert result["scroll"] <= result["width"]
    assert result["outside"] == []


def test_page_starts_at_the_top_bar(dashboard) -> None:
    """The hidden icon sprite must not reserve space above the page."""

    top = dashboard.evaluate(
        "document.querySelector('.topbar').getBoundingClientRect().top"
    )

    assert top <= 24
