"""Option rows (the necropsy form's status, assessment and final-result choices): a selected row's orange tick sits at the right, inside the row's own layout.

The old sheet draws a centre dot for any checked radio with `position:absolute; left:5px !important` on the same pseudo-element the tick uses, so the tick
landed on the left, over the first letter of the label (found on a real iPhone, 12 Oct 2026; it happens in every browser). Chromium and WebKit (iPhone Safari's
engine) are both checked, WebKit when it is installed."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from necropsy_seed import NECROPSY_SEED  # noqa: E402
from test_necropsy_species import _open_task  # noqa: E402
from test_trial_model_ui import _serve  # noqa: E402

GROUPS = ("rows_nec_status", "rows_nec_assessment", "rows2_nec_final")
TICKS = """() => [...document.querySelectorAll('[class*="st-key-rows"] [data-testid="stRadioOption"]:has(input:checked)')].map(o => {
  const after = getComputedStyle(o, '::after'); const label = o.querySelector('p').getBoundingClientRect(); const row = o.getBoundingClientRect();
  return {position: after.position, left: after.left, width: after.width, labelLeft: Math.round(label.left - row.left), rowWidth: Math.round(row.width)}; })"""


def _select_one_in_each_group(page: Page) -> None:
    for group in GROUPS:
        option = page.locator(f'[class*="st-key-{group}"] [data-testid="stRadioOption"]').first
        option.scroll_into_view_if_needed()
        option.click()
        page.wait_for_timeout(800)


def _assert_ticks_at_the_right(ticks: list) -> None:
    assert len(ticks) == 3, ticks
    for t in ticks:
        assert t["position"] == "static" and t["left"] == "auto", f"the tick must be in the row's layout, not placed by the old dot rule: {t}"
        assert t["width"] == "24px", t
        assert t["labelLeft"] >= 12, f"the label starts clear of the row's edge, nothing sits over it: {t}"


def test_a_selected_option_rows_tick_sits_at_the_right_not_over_the_label(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, NECROPSY_SEED) as url:
        _open_task(page, url, "Necropsy review")
        _select_one_in_each_group(page)
        _assert_ticks_at_the_right(page.evaluate(TICKS))


def test_the_same_in_webkit_the_engine_of_iphone_safari(tmp_path: Path) -> None:
    with sync_playwright() as playwright:
        try:
            browser = playwright.webkit.launch()
        except Exception as exc:  # WebKit is an optional extra download
            pytest.skip(f"WebKit is not installed: {exc}")
        data_dir = tmp_path / "d"; data_dir.mkdir()
        try:
            page = browser.new_context(**playwright.devices["iPhone 13"]).new_page()
            with _serve(data_dir, NECROPSY_SEED) as url:
                _open_task(page, url, "Necropsy review")
                _select_one_in_each_group(page)
                _assert_ticks_at_the_right(page.evaluate(TICKS))
        finally:
            browser.close()
