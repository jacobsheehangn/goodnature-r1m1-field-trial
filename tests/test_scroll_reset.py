"""A screen opens at its top: QA brief step 3 (first viewport) for the trial journey, and, since the owner's phone test, every screen.

scroll_to_top_once() used to target only elements Streamlit 1.60 does not scroll (it scrolls section[data-testid="stMain"]), so a
screen opened from a scrolled one opened part-way down whenever the browser kept some of the old position. The reset now targets
stMain on every screen and runs whenever the screen changes. The check form restored onto its Camera check scrolls to that instead
(test_resume_scrolls_to_camera_check.py); steps inside a journey flow (Set up's Preview after a long list, End trial's list ->
task -> preview) ask for the top as well."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from journey_seed import END_SEED, JOURNEY_SEED  # noqa: E402
from test_trial_model_ui import _serve  # noqa: E402
from test_trial_screens import _decide_unresolvable, _home, _open_set_up, _to_end_trial_from_the_visit  # noqa: E402

PHONE = {"width": 414, "height": 896}
MAIN_TOP = "() => Math.round(document.querySelector('section[data-testid=\"stMain\"]').scrollTop)"


def _scroll_to_bottom(page: Page) -> int:
    page.locator('section[data-testid="stMain"]').evaluate("el => { el.scrollTop = el.scrollHeight }")
    page.wait_for_timeout(400)
    return page.evaluate(MAIN_TOP)


def test_a_journey_screen_opened_from_a_scrolled_page_opens_at_its_top(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, JOURNEY_SEED) as url:
        _home(page, url)
        assert _scroll_to_bottom(page) > 0, "the Trap sites page must be scrolled for this to prove anything"
        page.get_by_role("button", name="Track as a trial", exact=True).click()
        expect(page.get_by_text("Builds currently running", exact=True)).to_be_visible(timeout=30_000)
        page.wait_for_timeout(1500)
        assert page.evaluate(MAIN_TOP) == 0, "Track as a trial opens at its top"


def test_the_end_trial_decision_list_opens_with_its_title_and_first_decision_on_screen(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, END_SEED) as url:
        _to_end_trial_from_the_visit(page, url)
        page.wait_for_timeout(1500)
        assert page.evaluate(MAIN_TOP) == 0
        title = page.get_by_text("End trial", exact=True).first.bounding_box()
        decide = page.get_by_role("button", name="Decide").first.bounding_box()
        assert title and title["y"] >= 0, f"the End trial title is on the first screen: {title}"
        assert decide and 0 <= decide["y"] and decide["y"] + decide["height"] <= PHONE["height"], f"the first Decide is on the first screen: {decide}"


def test_each_step_of_set_up_and_end_trial_opens_at_the_top(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, JOURNEY_SEED) as url:
        _open_set_up(page, url)
        page.get_by_role("button", name="Next: choose traps").click()
        expect(page.get_by_text("Set all unassigned to", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("radio", name="Build 4.3").first.click(); page.wait_for_timeout(500)
        assert _scroll_to_bottom(page) > 300, "step 2 is a long list"
        page.get_by_role("button", name="Preview activation").click()
        expect(page.get_by_text("This trial", exact=True)).to_be_visible(timeout=20_000)
        page.wait_for_timeout(1500)
        assert page.evaluate(MAIN_TOP) == 0, "Preview opens at its top, not at the bottom of the list it came from"
        assert page.get_by_text("Preview", exact=True).first.bounding_box()["y"] >= 0
    (tmp_path / "e").mkdir()
    with _serve(tmp_path / "e", END_SEED) as url:
        _to_end_trial_from_the_visit(page, url)
        _decide_unresolvable(page)
        expect(page.get_by_text("Marked unresolvable", exact=True)).to_be_visible(timeout=20_000)
        _decide_unresolvable(page)
        _scroll_to_bottom(page)
        page.get_by_role("button", name="Continue to preview").click()
        expect(page.get_by_text("What ending does", exact=True)).to_be_visible(timeout=20_000)
        page.wait_for_timeout(1500)
        assert page.evaluate(MAIN_TOP) == 0, "End trial's preview opens at its top"


# --- every screen opens at its top (owner's phone report, Deploy B test): "scroll down 50%, tap a button that opens another
# screen, and the 50% is carried over". Streamlit's page area collapses and regrows while a screen is swapped, and how much
# of the old position survives is down to timing: Chromium on a laptop clamps it to 0, WebKit (the engine of iPhone Safari)
# keeps part of it. So the screens are opened here in both engines.

def _half_way_down(page: Page) -> int:
    page.locator('section[data-testid="stMain"]').evaluate("el => { el.scrollTop = (el.scrollHeight - el.clientHeight) / 2 }")
    page.wait_for_timeout(400)
    return page.evaluate(MAIN_TOP)


def _lands_at_the_top_and_stays(page: Page, what: str) -> None:
    page.wait_for_timeout(1500)
    seen = [page.evaluate(MAIN_TOP)]
    for _ in range(3):
        page.wait_for_timeout(500)
        seen.append(page.evaluate(MAIN_TOP))
    assert seen == [0, 0, 0, 0], f"{what} opens at its top and stays there, not part-way down: {seen}"


def _walk_the_screens(page: Page, url: str) -> None:
    sites = page.get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).first
    trap_list = page.get_by_text("Select the trap you are standing at.", exact=True)
    page.goto(url, wait_until="domcontentloaded"); expect(sites).to_be_visible(timeout=40_000); page.wait_for_timeout(1500)
    assert _half_way_down(page) > 100, "Trap sites must be scrolled for this to prove anything"
    sites.click(); expect(trap_list).to_be_visible(timeout=30_000)
    _lands_at_the_top_and_stays(page, "the trap list opened from Trap sites")
    assert _half_way_down(page) > 100, "the trap list must be scrolled for this to prove anything"
    page.get_by_role("button", name="Check", exact=True).first.click(); expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)
    _lands_at_the_top_and_stays(page, "the check form opened from the trap list")
    assert _half_way_down(page) > 50, "the check form must be scrolled for this to prove anything"
    page.get_by_role("button", name=re.compile("Back to trap selector")).click(); expect(trap_list).to_be_visible(timeout=30_000)
    _lands_at_the_top_and_stays(page, "the trap list reached from the check form")
    assert _half_way_down(page) > 50, "the trap list must be scrolled for this to prove anything"
    page.get_by_role("link", name=re.compile(r"^Follow-ups")).click(); expect(page.get_by_role("heading", name="Follow-ups")).to_be_visible(timeout=30_000)
    _lands_at_the_top_and_stays(page, "Follow-ups opened from the top navigation")
    _half_way_down(page)
    page.get_by_role("link", name=re.compile(r"^Trial performance")).click(); expect(page.get_by_role("heading", name="Trial performance")).to_be_visible(timeout=30_000)
    _lands_at_the_top_and_stays(page, "Trial performance opened from the top navigation")


def test_every_screen_opens_at_its_top_in_chromium(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 664})  # an iPhone 13's page area, so the check form has room to scroll
    with _serve(data_dir, END_SEED) as url:
        _walk_the_screens(page, url)


def test_every_screen_opens_at_its_top_in_webkit_the_engine_of_iphone_safari(tmp_path: Path) -> None:
    with sync_playwright() as playwright:
        try:
            browser = playwright.webkit.launch()
        except Exception as exc:  # WebKit is an optional extra download
            pytest.skip(f"WebKit is not installed: {exc}")
        data_dir = tmp_path / "d"; data_dir.mkdir()
        try:
            page = browser.new_context(**playwright.devices["iPhone 13"]).new_page()
            with _serve(data_dir, END_SEED) as url:
                _walk_the_screens(page, url)
        finally:
            browser.close()


def test_returning_from_a_review_opened_in_end_trial_lands_on_end_trial_at_its_top(page: Page, tmp_path: Path) -> None:
    """That return is a switch_page that sets no navigation flag: the reset has to come from the screen having changed."""
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, END_SEED) as url:
        _to_end_trial_from_the_visit(page, url)
        page.get_by_role("button", name="Decide").first.click()
        page.get_by_role("button", name="Review now", exact=True).click()
        expect(page.get_by_text("Complete this review", exact=True)).to_be_visible(timeout=20_000)
        page.wait_for_timeout(1500)
        assert _half_way_down(page) > 100, "the review form must be scrolled for this to prove anything"
        page.get_by_role("button", name="← Back to End trial").click()
        expect(page.get_by_text("Needs your decision", exact=True)).to_be_visible(timeout=30_000)
        _lands_at_the_top_and_stays(page, "End trial reached from the review form")


def test_a_screen_the_operator_starts_scrolling_straight_away_is_not_pulled_back_to_the_top(page: Page, tmp_path: Path) -> None:
    """The reset retries for about a second; it has to give way the moment the operator touches the page."""
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, END_SEED) as url:
        page.goto(url, wait_until="domcontentloaded")
        sites = page.get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).first
        expect(sites).to_be_visible(timeout=40_000); page.wait_for_timeout(1500)
        sites.click()
        expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
        expect(page.locator('iframe[srcdoc*="handOver"]')).to_have_count(1, timeout=10_000)  # the reset is running
        page.wait_for_timeout(150)
        page.mouse.move(200, 500); page.mouse.wheel(0, 300)
        page.wait_for_timeout(1800)
        assert page.evaluate(MAIN_TOP) > 100, "the operator's own scroll stays where they put it"
