"""QA brief step 3 (first viewport): the trial journey screens open at their top.

The reset in scroll_to_top_once() never targeted the element Streamlit 1.60 actually scrolls
(section[data-testid="stMain"]), so a page opened from a scrolled page opened part-way down: on origin/main too.
Only the journey screens get the real target (the check page's resume-to-camera scroll and the Data & records forms were built
around the old behaviour: test_resume_scrolls_to_camera_check.py). Steps inside a journey flow (Set up's Preview after a long
list, End trial's list -> task -> preview) ask for the top as well."""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import Page, expect

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
