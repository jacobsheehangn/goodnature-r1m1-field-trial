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
import check_form as cf
from playwright.sync_api import Page, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
import task_form as tf  # noqa: E402
from journey_seed import END_SEED, JOURNEY_SEED  # noqa: E402
from test_trial_model_ui import _serve  # noqa: E402
from test_trial_screens import _choose, _decide_unresolvable, _home, _open_set_up, _to_end_trial_from_the_visit  # noqa: E402

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

def _trap_list_marker(page: Page):
    """The trap list is open: its sub-line before Phase 7b removed it, the Finish site check button on every line."""
    return page.get_by_text("Select the trap you are standing at.", exact=True).or_(page.get_by_role("button", name=re.compile(r"^Finish site check"))).first


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
    trap_list = _trap_list_marker(page)
    page.goto(url, wait_until="domcontentloaded"); expect(sites).to_be_visible(timeout=40_000); page.wait_for_timeout(1500)
    assert _half_way_down(page) > 100, "Trap sites must be scrolled for this to prove anything"
    sites.click(); expect(trap_list).to_be_visible(timeout=30_000)
    _lands_at_the_top_and_stays(page, "the trap list opened from Trap sites")
    assert _half_way_down(page) > 100, "the trap list must be scrolled for this to prove anything"
    page.get_by_role("button", name="Check", exact=True).first.click(); expect(page.get_by_text("All as expected?", exact=True)).to_be_visible(timeout=30_000)
    _lands_at_the_top_and_stays(page, "the check form opened from the trap list")
    assert _half_way_down(page) > 10, "the check form must be scrolled for this to prove anything"  # a short form on the 7b screens
    page.get_by_role("button", name=re.compile("Back to trap list")).click(); expect(trap_list).to_be_visible(timeout=30_000)
    _lands_at_the_top_and_stays(page, "the trap list reached from the check form")
    assert _half_way_down(page) > 10, "the trap list must be scrolled for this to prove anything"
    if not page.get_by_role("link", name=re.compile(r"^Follow-ups")).count():  # the 7b trap list hides the top navigation
        page.get_by_role("button", name="Exit to Trap sites").click(); expect(sites).to_be_visible(timeout=30_000)
        _lands_at_the_top_and_stays(page, "Trap sites reached from the trap list")
        assert _half_way_down(page) > 100, "Trap sites must be scrolled for this to prove anything"
    page.get_by_role("link", name=re.compile(r"^Follow-ups")).click(); expect(page.get_by_role("heading", name="Follow-ups")).to_be_visible(timeout=30_000)
    _lands_at_the_top_and_stays(page, "Follow-ups opened from the top navigation")
    _half_way_down(page)
    performance = page.get_by_role("link", name=re.compile(r"^Trial performance"))
    if not performance.count():  # on a phone the 7b navigation keeps it in the More menu
        page.get_by_role("button", name="More", exact=True).click()
        performance = page.get_by_role("dialog", name="More").get_by_role("link", name="Trial performance", exact=True)
    performance.click(); expect(page.get_by_role("heading", name="Trial performance")).to_be_visible(timeout=30_000)
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
        expect(page.get_by_role("heading", name="Camera review", exact=True)).to_be_visible(timeout=20_000)
        page.wait_for_timeout(1500)
        assert _half_way_down(page) > 100, "the review form must be scrolled for this to prove anything"
        page.get_by_role("button", name="Back to End trial").click()
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
        expect(_trap_list_marker(page)).to_be_visible(timeout=30_000)
        expect(page.locator('iframe[srcdoc*="handOver"]')).to_have_count(1, timeout=10_000)  # the reset is running
        page.wait_for_timeout(150)
        page.mouse.move(200, 500); page.mouse.wheel(0, 300)
        page.wait_for_timeout(1800)
        assert page.evaluate(MAIN_TOP) > 100, "the operator's own scroll stays where they put it"


# --- every screen swap, in place or not (the owner's phone test of the necropsy follow-up, 12 Oct): the Follow-ups page shows a
# task in place of its list without navigating, so a list scrolled half-way opened its task half-way down, and the success message
# on the list a saved task returns to was above the top of the screen.

def _follow_ups_seed() -> str:
    return END_SEED + """
    d = app.load_data()
    traps = d["Traps"][(d["Traps"]["Site ID"] == "MAN") & (d["Traps"]["Status"] == "Active")]["Trap ID"].tolist()
    for i in range(14):
        app.add_followup(d, "Camera review", "MAN", traps[i % len(traps)], "VIS-WALK-1", "W-F%d" % i, "BAG-%03d" % i, "filler task %d" % i, "d", "Low")
    app.save_data(d)
"""


def _walk_the_follow_ups(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    expect(page.get_by_role("link", name=re.compile(r"^Follow-ups")).first).to_be_visible(timeout=40_000); page.wait_for_timeout(1500)
    page.get_by_role("link", name=re.compile(r"^Follow-ups")).first.click()
    expect(page.get_by_role("heading", name="Follow-ups")).to_be_visible(timeout=30_000); page.wait_for_timeout(1500)
    assert _half_way_down(page) > 300, "the Follow-ups list must be long enough to scroll for this to prove anything"
    review = page.get_by_role("button", name="Review", exact=True)
    expect(review.first).to_be_visible(); page.locator('section[data-testid="stMain"]').evaluate("el => { el.scrollTop = el.scrollHeight }"); page.wait_for_timeout(400)
    assert page.evaluate(MAIN_TOP) > 300
    review.last.click()
    expect(page.get_by_role("button", name="Back to task list")).to_be_visible(timeout=30_000)
    _lands_at_the_top_and_stays(page, "a follow-up task opened from a scrolled list")
    page.get_by_role("button", name="Back to task list").click()
    expect(page.get_by_role("heading", name="Follow-ups")).to_be_visible(timeout=30_000)
    _lands_at_the_top_and_stays(page, "the Follow-ups list reached from a task")


def test_a_follow_up_task_opens_and_closes_at_the_top_in_chromium(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 664})
    with _serve(data_dir, _follow_ups_seed()) as url:
        _walk_the_follow_ups(page, url)


def test_a_follow_up_task_opens_and_closes_at_the_top_in_webkit(tmp_path: Path) -> None:
    with sync_playwright() as playwright:
        try:
            browser = playwright.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not installed: {exc}")
        data_dir = tmp_path / "d"; data_dir.mkdir()
        try:
            page = browser.new_context(**playwright.devices["iPhone 13"]).new_page()
            with _serve(data_dir, _follow_ups_seed()) as url:
                _walk_the_follow_ups(page, url)
        finally:
            browser.close()


def test_the_success_message_of_a_saved_task_is_on_screen_when_the_list_returns(page: Page, tmp_path: Path) -> None:
    """Saving a follow-up task returns to the list with a success message above it: the page has to be at the top for that to be seen."""
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 664})
    with _serve(data_dir, _follow_ups_seed()) as url:
        page.goto(url, wait_until="domcontentloaded")
        expect(page.get_by_role("link", name=re.compile(r"^Follow-ups")).first).to_be_visible(timeout=40_000); page.wait_for_timeout(1500)
        page.get_by_role("link", name=re.compile(r"^Follow-ups")).first.click()
        expect(page.get_by_role("heading", name="Follow-ups")).to_be_visible(timeout=30_000); page.wait_for_timeout(1500)
        page.get_by_text("Camera review", exact=True).first.locator("xpath=ancestor::div[.//button][1]").get_by_role("button", name="Review", exact=True).click()
        expect(page.get_by_role("button", name="Back to task list")).to_be_visible(timeout=30_000); page.wait_for_timeout(1500)
        tf.choose(page, "Camera evidence usable?", "No")
        page.locator('section[data-testid="stMain"]').evaluate("el => { el.scrollTop = el.scrollHeight }"); page.wait_for_timeout(400)
        assert page.evaluate(MAIN_TOP) > 50, "the review form must be scrolled for this to prove anything"
        page.get_by_role("button", name="Save camera review").click()
        saved = page.get_by_text("Camera review saved", exact=True)
        expect(saved).to_be_visible(timeout=60_000)
        _lands_at_the_top_and_stays(page, "the Follow-ups list after a saved review")
        box = saved.bounding_box()
        assert box and 0 <= box["y"] < 664, f"the success message is on the first screen: {box}"


# --- the old screen's last buttons must not show under the new screen while it is being drawn (the owner's "six buttons" when
# finishing a site check). The server is slowed by delaying what it sends, so the drawing takes seconds, as on a phone.

SCREEN_LOG = """() => { window.__frames = []; let last = '';
  const tick = () => { const m = document.querySelector('section[data-testid="stMain"]');
    const shown = [...m.querySelectorAll('button')].filter(b => b.getClientRects().length > 0 && b.innerText.trim()).map(b => b.innerText.trim());
    const heading = [...m.querySelectorAll('h1, .r1-title')].some(h => h.getClientRects().length > 0);
    const oldScreen = shown.filter(t => /^(Finish site check|Pause and return|Finish visit and end trial)/.test(t)).length;
    const newScreen = shown.filter(t => /^(Start checking|Resume checking|Track as a trial|Open follow-ups)/.test(t)).length;
    const key = oldScreen + '/' + newScreen + '/' + heading; if (key !== last) { window.__frames.push([Math.round(performance.now()), oldScreen, newScreen, heading]); last = key; }
    requestAnimationFrame(tick); }; requestAnimationFrame(tick); }"""


def _slow_the_server(page: Page, delay_ms: int) -> None:
    import time

    def route(ws):
        server = ws.connect_to_server()
        server.on_message(lambda message: (time.sleep(delay_ms / 1000), ws.send(message)))
    page.route_web_socket("**/_stcore/stream", route)


def test_the_old_screens_last_buttons_never_show_under_the_new_screen(page: Page, tmp_path: Path) -> None:
    all_checked = END_SEED.replace("for t in r1[:3]:", "for t in r1:")
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 664})
    _slow_the_server(page, 90)
    with _serve(data_dir, all_checked) as url:
        page.goto(url, wait_until="domcontentloaded")
        resume = page.get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).first
        expect(resume).to_be_visible(timeout=60_000); page.wait_for_timeout(1500); resume.click()
        finish = page.get_by_role("button", name=re.compile(r"^Finish site check")); expect(finish).to_be_visible(timeout=60_000); page.wait_for_timeout(3000)
        finish.scroll_into_view_if_needed(); page.evaluate(SCREEN_LOG); finish.click()
        page.wait_for_timeout(14_000)
        frames = page.evaluate("window.__frames")
    assert any(f[2] for f in frames), f"the next screen was never drawn: {frames}"
    both = [f for f in frames if f[1] and f[2]]
    assert not both, f"the old screen's buttons were on screen under the new screen's: {both}"


def test_a_tap_that_changes_nothing_on_screen_does_not_blank_the_page_first(page: Page, tmp_path: Path) -> None:
    """The rule that hides the old screen applies only to the run that changes the screen: the next tap, in place, keeps its screen."""
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 664})
    _slow_the_server(page, 90)
    with _serve(data_dir, END_SEED) as url:
        page.goto(url, wait_until="domcontentloaded")
        link = page.get_by_role("link", name=re.compile(r"^Follow-ups")).first
        expect(link).to_be_visible(timeout=60_000); page.wait_for_timeout(1500); link.click()   # a change of screen: the hide rule is on for that run
        expect(page.get_by_role("heading", name="Follow-ups")).to_be_visible(timeout=60_000); page.wait_for_timeout(4000)
        page.evaluate(SCREEN_LOG)
        segmented = page.locator('[class*="st-key-seg_followup_priority"] button').filter(has_text="High")   # the 7b screens use a segmented control
        if segmented.count():
            segmented.first.click()   # in place
        else:
            page.get_by_label("Priority").first.click(); page.get_by_role("option", name="High").click()   # in place
        page.wait_for_timeout(9000)
        frames = page.evaluate("window.__frames")
    assert frames and all(f[3] for f in frames), f"the page was blanked during an in-place tap: {frames}"


# --- the Add/Edit panels on Trial setup sit in a second column, which stacks below the whole list on a phone: opening one has to
# bring it into view (on the iPhone profile "Add trap" opened its form 4000 px down a 5200 px page, so nothing seemed to happen).

def _panel_walk(page: Page, url: str) -> None:
    page.goto(url + "/trial-setup", wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="Trial setup")).to_be_visible(timeout=40_000); page.wait_for_timeout(2500)
    for section, button, heading in (("Traps", "Add trap", "Add trap"), ("Trap sites", "Add site", "Add site"), ("Builds", "Add build", "Add build")):
        page.get_by_role("radio", name=section, exact=True).click(); page.wait_for_timeout(2000)
        page.locator('section[data-testid="stMain"]').evaluate("el => { el.scrollTop = 0 }")
        page.get_by_role("button", name=button, exact=True).click()
        panel = page.get_by_role("heading", name=heading).first
        expect(panel).to_be_visible(timeout=30_000); page.wait_for_timeout(2200)
        box = panel.bounding_box()
        assert box and 0 <= box["y"] < 400, f"{button}: the panel's heading is near the top of the screen, not off it: {box}"
        page.get_by_role("button", name="Cancel").first.click()
        expect(page.get_by_role("heading", name=heading)).to_have_count(0, timeout=30_000)
        _lands_at_the_top_and_stays(page, f"Trial setup after closing the {button} panel")


def test_the_add_and_edit_panels_come_into_view_in_chromium(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 664})
    with _serve(data_dir, END_SEED) as url:
        _panel_walk(page, url)


def test_the_add_and_edit_panels_come_into_view_in_webkit(tmp_path: Path) -> None:
    with sync_playwright() as playwright:
        try:
            browser = playwright.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not installed: {exc}")
        data_dir = tmp_path / "d"; data_dir.mkdir()
        try:
            page = browser.new_context(**playwright.devices["iPhone 13"]).new_page()
            with _serve(data_dir, END_SEED) as url:
                _panel_walk(page, url)
        finally:
            browser.close()


# --- Data & records > Trial history > a test window's Review panel (the same anchor as the Add/Edit panels, walked on its own).

ANCHOR_TOP = """() => { const a = document.getElementById('r1m1-panel-anchor'); const m = document.querySelector('section[data-testid="stMain"]');
  return a ? Math.round(a.getBoundingClientRect().top - m.getBoundingClientRect().top) : null; }"""


def _window_panel_walk(page: Page, url: str) -> None:
    page.goto(url + "/data-records", wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="Data & records")).to_be_visible(timeout=40_000); page.wait_for_timeout(2500)
    page.get_by_role("button", name="Trial periods", exact=True).click()
    expect(page.get_by_role("heading", name="Trial periods")).to_be_visible(timeout=30_000); page.wait_for_timeout(2500)
    page.get_by_role("radio", name="All", exact=True).click(); page.wait_for_timeout(2500)
    review = page.get_by_role("button", name="Review", exact=True)
    assert review.count() > 4, "the list must be long enough to scroll for this to prove anything"
    page.locator('section[data-testid="stMain"]').evaluate("el => { el.scrollTop = (el.scrollHeight - el.clientHeight) / 3 }"); page.wait_for_timeout(500)
    assert page.evaluate(MAIN_TOP) > 300
    visible_review = [review.nth(i) for i in range(review.count()) if review.nth(i).is_visible() and 0 <= review.nth(i).bounding_box()["y"] < 600]
    assert visible_review, "a Review button must be on screen to tap"
    visible_review[0].click()
    expect(page.get_by_role("button", name="Back to Trial periods", exact=True)).to_be_attached(timeout=30_000); page.wait_for_timeout(2500)
    top = page.evaluate(ANCHOR_TOP)
    assert top is not None and 0 <= top < 400, f"the test-window panel is brought into view, not left far below the list: its top is at {top}px of a 664px screen"
    page.get_by_role("button", name="Back to Trial periods", exact=True).click()
    expect(page.get_by_role("button", name="Back to Trial periods", exact=True)).to_have_count(0, timeout=30_000)
    _lands_at_the_top_and_stays(page, "Trial periods after closing the panel")


def test_the_data_and_records_test_window_panel_comes_into_view_in_chromium(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 664})
    with _serve(data_dir, END_SEED) as url:
        _window_panel_walk(page, url)


def test_the_data_and_records_test_window_panel_comes_into_view_in_webkit(tmp_path: Path) -> None:
    with sync_playwright() as playwright:
        try:
            browser = playwright.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not installed: {exc}")
        data_dir = tmp_path / "d"; data_dir.mkdir()
        try:
            page = browser.new_context(**playwright.devices["iPhone 13"]).new_page()
            with _serve(data_dir, END_SEED) as url:
                _window_panel_walk(page, url)
        finally:
            browser.close()


# --- the owner's phone (12 Oct): on a trap whose check had been started before, tapping "Carcass collected? Yes" threw the page down to the
# Camera check. The "scroll to where you left off" is for arriving on the check page with a saved draft; Streamlit drops the state of
# widgets that are not on screen, so the draft was restored again on a later rerun of the same visit and the scroll fired mid-form.
# Live on main too (c21218d); found because the owner's retests left a draft on the trap.

def _carcass_after_a_saved_draft(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    start = page.get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).first
    expect(start).to_be_visible(timeout=40_000); page.wait_for_timeout(1500); start.click()
    expect(_trap_list_marker(page)).to_be_visible(timeout=30_000)
    camera_trap = None
    for i in range(6):   # a trap with a camera
        page.get_by_role("button", name="Check", exact=True).nth(i).click()
        expect(page.get_by_text("All as expected?", exact=True)).to_be_visible(timeout=30_000)
        cf.select(page.get_by_role("radio", name="Dead animal found")); page.wait_for_timeout(1500)
        cf.select(page.get_by_role("radiogroup", name="Carcass collected?").get_by_role("radio", name="Yes", exact=True)); page.wait_for_timeout(2000)
        if page.get_by_text("Camera working and covering the trap?", exact=True).count():
            camera_trap = i; break
        page.get_by_role("button", name=re.compile("Back to trap list")).click(); expect(_trap_list_marker(page)).to_be_visible(timeout=30_000)
    assert camera_trap is not None, "no trap with a camera in the first six"
    page.wait_for_timeout(1500)
    page.get_by_role("button", name=re.compile("Back to trap list")).click(); expect(_trap_list_marker(page)).to_be_visible(timeout=30_000)
    # the same trap again: a draft is waiting
    page.get_by_role("button", name="Check", exact=True).nth(camera_trap).click()
    expect(page.get_by_text("What you found", exact=True)).to_be_visible(timeout=30_000); page.wait_for_timeout(3000)
    assert page.evaluate(MAIN_TOP) > 500, "arriving with a saved draft still lands on the Camera check (the field-report feature)"
    carcass = page.get_by_role("radiogroup", name="Carcass collected?")
    carcass.scroll_into_view_if_needed(); page.wait_for_timeout(600)
    for answer in ("No", "Yes"):
        before = page.evaluate(MAIN_TOP)
        cf.select(carcass.get_by_role("radio", name=answer, exact=True)); page.wait_for_timeout(3000)
        after = page.evaluate(MAIN_TOP)
        assert abs(after - before) < 80, f"tapping Carcass collected = {answer} must not move the page (it went from {before} to {after})"


def test_answering_the_check_form_after_a_saved_draft_does_not_throw_the_page_in_chromium(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 664})
    with _serve(data_dir, END_SEED) as url:
        _carcass_after_a_saved_draft(page, url)


def test_answering_the_check_form_after_a_saved_draft_does_not_throw_the_page_in_webkit(tmp_path: Path) -> None:
    with sync_playwright() as playwright:
        try:
            browser = playwright.webkit.launch()
        except Exception as exc:
            pytest.skip(f"WebKit is not installed: {exc}")
        data_dir = tmp_path / "d"; data_dir.mkdir()
        try:
            page = browser.new_context(**playwright.devices["iPhone 13"]).new_page()
            with _serve(data_dir, END_SEED) as url:
                _carcass_after_a_saved_draft(page, url)
        finally:
            browser.close()
