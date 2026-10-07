"""Phase 7b, Navigation (TRIAL_LIFECYCLE_BRIEF.md "Navigation - decided"): one row on a phone (Trap sites, Follow-ups with its
count, More), four items on desktop, the count's definition and freshness, the current state, and where the navigation shows.
Local test data only."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from journey_seed import END_SEED, JOURNEY_SEED  # noqa: E402
from necropsy_seed import NECROPSY_SEED  # noqa: E402
from test_trial_model_ui import _serve, _sheet  # noqa: E402
from test_trial_screens import _card, _home  # noqa: E402

PHONE, DESKTOP = {"width": 414, "height": 896}, {"width": 1280, "height": 900}
FOLLOWUPS = re.compile(r"^Follow-ups( \d+)?$")
# Each pill as the person reads it: its text plus the count drawn after it (the count is CSS content, not text).
LABELS = """(root) => [...document.querySelectorAll(root + ' [data-testid="stPageLink"] a, ' + root + ' [data-testid="stPopoverButton"]')].map(e => {
  const c = getComputedStyle(e, '::after').content; const badge = (c && c !== 'none' && c !== 'normal') ? c.replace(/"/g, '') : '';
  return [(e.innerText.trim().replace(/\\s+/g, ' ') + (badge ? ' ' + badge : '')), Math.round(e.getBoundingClientRect().top), Math.round(e.getBoundingClientRect().height)]; })"""
BADGE = "(sel) => { const c = getComputedStyle(document.querySelector(sel), '::after').content; return (c && c !== 'none' && c !== 'normal') ? c.replace(/\"/g, '') : ''; }"


def _visible(page: Page, key: str) -> bool:
    return page.evaluate("(k) => getComputedStyle(document.querySelector('.st-key-' + k)).display !== 'none'", key)


# --- the two layouts ---------------------------------------------------------------------------------------------------

def test_the_phone_navigation_is_one_row_with_the_follow_up_count_and_a_more_menu(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        assert _visible(page, "nav_phone") and not _visible(page, "nav_desktop")
        items = page.evaluate(LABELS, ".st-key-nav_phone")
        assert [i[0] for i in items] == ["Trap sites", "Follow-ups 4", "More"], items
        assert len({i[1] for i in items}) == 1, f"all three are on one row: {items}"
        assert all(i[2] >= 44 for i in items), f"nothing tapped is under 44px: {items}"


def test_the_desktop_navigation_has_four_items_and_switches_at_700_px(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(DESKTOP)
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        assert _visible(page, "nav_desktop") and not _visible(page, "nav_phone")
        assert [i[0] for i in page.evaluate(LABELS, ".st-key-nav_desktop")] == ["Trap sites", "Follow-ups 4", "Trial performance", "Administration"]
        page.set_viewport_size({"width": 700, "height": 900}); page.wait_for_timeout(500)
        assert _visible(page, "nav_phone") and not _visible(page, "nav_desktop"), "700px is still a phone"
        page.set_viewport_size({"width": 701, "height": 900}); page.wait_for_timeout(500)
        assert _visible(page, "nav_desktop") and not _visible(page, "nav_phone"), "701px is desktop"


def test_every_administration_item_stays_reachable_on_a_phone(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        page.get_by_role("button", name="More", exact=True).click()
        menu = page.get_by_role("dialog", name="More")
        expect(menu).to_be_visible(timeout=10_000)
        text = menu.inner_text()
        for needed in ("Trial performance", "Administration", "Traps", "Trial setup", "Data & records", "Data quality", "Operator", "Sign out"):
            assert needed in text, f"{needed!r} is in the More menu: {text!r}"
        assert text.index("Trial performance") < text.index("Administration") < text.index("Traps") < text.index("Data quality") < text.index("Sign out")
        for link, path in (("Traps", "/traps"), ("Data & records", "/data-records")):
            menu.get_by_role("link", name=link, exact=True).click()
            expect(page).to_have_url(re.compile(re.escape(path) + r"$"), timeout=20_000)
            page.get_by_role("button", name="More", exact=True).click()
            menu = page.get_by_role("dialog", name="More")
        menu.get_by_role("link", name="Trial performance", exact=True).click()
        expect(page).to_have_url(re.compile(r"/trial-performance$"), timeout=20_000)
        expect(page.get_by_text("Do we have enough evidence to launch?", exact=False)).to_be_visible(timeout=20_000)


# --- the count -----------------------------------------------------------------------------------------------------------

def test_the_count_is_what_the_follow_ups_page_lists_by_default_and_is_hidden_at_zero(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(DESKTOP)
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        shown = int(page.evaluate(BADGE, ".st-key-nav_desktop a[href$='follow-ups']"))
        followups = _sheet(data_dir, "Followups")
        assert shown == int((followups["Status"] == "Open").sum()) == 4
        page.get_by_role("link", name=FOLLOWUPS).click()
        expect(page.get_by_text("Review a task directly from its row.", exact=True)).to_be_visible(timeout=20_000)
        assert page.get_by_role("button", name="Review", exact=True).count() == shown, "the badge counts the tasks the page lists as open by default"
    (tmp_path / "e").mkdir()
    with _serve(tmp_path / "e", JOURNEY_SEED) as url:
        _home(page, url)
        assert not _sheet(tmp_path / "e", "Followups").query("Status == 'Open'").shape[0]
        expect(page.get_by_role("link", name="Follow-ups", exact=True)).to_be_visible()
        assert page.evaluate(BADGE, ".st-key-nav_desktop a[href$='follow-ups']") == "", "no badge at zero"


def test_the_count_is_right_on_the_screen_you_land_on_after_completing_a_task(page: Page, tmp_path: Path) -> None:
    """The navigation is drawn near the top of the run: prove a completion does not leave the count one run behind."""
    from test_necropsy_species import _fill_the_form, _open_task  # noqa: PLC0415
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(DESKTOP)
    with _serve(data_dir, NECROPSY_SEED) as url:
        _open_task(page, url, "Necropsy review")
        expect(page.get_by_role("link", name=re.compile(r"^Follow-ups 1$"))).to_be_visible(timeout=15_000)
        _fill_the_form(page, weight="11–20 g", final="No", assessment="Does not support humane kill")
        page.get_by_role("button", name="Save necropsy review").click()
        expect(page.get_by_text("Necropsy review saved", exact=True)).to_be_visible(timeout=60_000)
        expect(page.get_by_role("link", name="Follow-ups", exact=True)).to_be_visible(timeout=15_000)  # "Follow-ups 1" would be one run behind
        followups = _sheet(data_dir, "Followups")
        assert not (followups["Status"] == "Open").any(), "the task really is complete"


def _open_count_is(page: Page, n: int) -> None:
    """The Follow-ups pill reads "Follow-ups N" exactly: one run behind would read N+1."""
    expect(page.get_by_role("link", name=re.compile(rf"^Follow-ups {n}$"))).to_be_visible(timeout=15_000)
    assert page.get_by_role("link", name=re.compile(rf"^Follow-ups {n + 1}$")).count() == 0, f"the count is one run behind (still {n + 1})"


def test_the_count_is_right_after_a_camera_review_is_saved_from_the_follow_ups_list(page: Page, tmp_path: Path) -> None:
    """The second completion path: END_SEED has four open tasks, so a count one run behind would read 4, not 3."""
    from test_necropsy_species import _open_task  # noqa: PLC0415
    from test_trial_screens import _choose  # noqa: PLC0415
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(DESKTOP)
    with _serve(data_dir, END_SEED) as url:
        _open_task(page, url, "Camera review")
        _open_count_is(page, 4)
        page.wait_for_timeout(1_500)
        _choose(page, "Camera evidence usable", "No")
        page.get_by_role("button", name="Save camera review").click()
        expect(page.get_by_text("Camera review saved", exact=True)).to_be_visible(timeout=60_000)
        _open_count_is(page, 3)
        followups = _sheet(data_dir, "Followups")
        assert (followups["Status"] == "Open").sum() == 3 and followups[followups["Follow-up Type"] == "Camera review"].iloc[0]["Status"] == "Complete"


def test_the_count_is_right_after_a_camera_resolution_is_saved_from_the_follow_ups_list(page: Page, tmp_path: Path) -> None:
    """The third completion path (a hardware task), which also ends on the Follow-ups list."""
    from test_button_loading_feedback_tier2 import _click_until_busy_or_done  # noqa: PLC0415
    from test_necropsy_species import _open_task  # noqa: PLC0415
    from test_trial_screens import _choose  # noqa: PLC0415
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(DESKTOP)
    with _serve(data_dir, END_SEED) as url:
        _open_task(page, url, "Camera issue")
        _open_count_is(page, 4)
        page.wait_for_timeout(1_500)
        _choose(page, "Camera outcome", "Fixed and now working")
        _choose(page, "Camera now ready and covering the trap", "Yes")
        _choose(page, "Past test-window evidence", "Still usable")
        page.get_by_label("Resolution notes").fill("Battery replaced and the angle checked.")
        page.wait_for_timeout(1_500)
        _click_until_busy_or_done(page, page.get_by_role("button", name="Save camera resolution"), "Saving…", "Camera resolution saved")
        expect(page.get_by_text("Camera resolution saved", exact=True)).to_be_visible(timeout=60_000)
        _open_count_is(page, 3)
        followups = _sheet(data_dir, "Followups")
        assert (followups["Status"] == "Open").sum() == 3 and followups[followups["Follow-up Type"] == "Camera issue"].iloc[0]["Status"] == "Complete"


# --- the current state ---------------------------------------------------------------------------------------------------

def test_the_current_page_is_shown_and_the_menu_pill_takes_the_state_when_a_page_inside_it_is_current(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        # The shipped disabled-link mechanism is the "you are here": a disabled link, restyled.
        current = lambda root: page.evaluate("(r) => [...document.querySelectorAll(r + ' a[disabled]')].map(a => a.getAttribute('href') || '')", root)
        assert [h.rsplit("/", 1)[-1] for h in current(".st-key-nav_phone")] == ["trap-sites"] or current(".st-key-nav_phone") == [""] or len(current(".st-key-nav_phone")) == 1
        page.get_by_role("link", name=FOLLOWUPS).click()
        expect(page.get_by_text("Review a task directly from its row.", exact=True)).to_be_visible(timeout=20_000)
        assert [h.rsplit("/", 1)[-1] for h in current(".st-key-nav_phone")] == ["follow-ups"]
        assert page.locator('[class*="st-key-navmore_on"]').count() == 0
        page.get_by_role("button", name="More", exact=True).click()
        page.get_by_role("dialog", name="More").get_by_role("link", name="Data quality").click()
        expect(page).to_have_url(re.compile(r"/data-quality$"), timeout=20_000)
        page.wait_for_timeout(800)
        assert page.locator('[class*="st-key-navmore_on_phone"]').count() == 1, "More takes the current state while Data quality is current"
        page.set_viewport_size(DESKTOP); page.wait_for_timeout(500)
        assert page.locator('[class*="st-key-navmore_on_desktop"]').count() == 1, "so does Administration on desktop"


# --- where it shows ------------------------------------------------------------------------------------------------------

def test_visit_mode_and_the_flows_have_no_navigation_and_every_other_page_has_it(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    nav = lambda: page.locator(".st-key-app_nav").count()
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        assert nav() == 1, "Trap sites"
        _card(page, "Mangaroa Farm").get_by_role("button", name="Trial overview", exact=True).click()
        expect(page.get_by_text("Evidence waiting", exact=True)).to_be_visible(timeout=20_000)
        assert nav() == 1, "the trial hub"
        page.get_by_role("button", name="Resume checking", exact=True).click()
        expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=20_000)
        assert nav() == 0, "the trap list (visit mode)"
        page.get_by_role("button", name="Check", exact=True).first.click()
        expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=20_000)
        assert nav() == 0, "the check form"
        page.get_by_role("button", name=re.compile("Back to trap")).first.click()
        expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("button", name=re.compile("Finish visit and end trial")).click()
        expect(page.get_by_text("Needs your decision", exact=True)).to_be_visible(timeout=20_000)
        assert nav() == 0, "End trial"
        page.get_by_role("button", name=re.compile("Back to visit")).click()
        expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("button", name="Pause and return to Trap sites").click()
        expect(page.get_by_role("heading", name="Trap sites", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("link", name=FOLLOWUPS).click()
        expect(page.get_by_text("Review a task directly from its row.", exact=True)).to_be_visible(timeout=20_000)
        assert nav() == 1, "Follow-ups"
        page.get_by_role("button", name="Review", exact=True).first.click()
        expect(page.get_by_role("button", name=re.compile("Back to task list"))).to_be_visible(timeout=20_000)
        assert nav() == 1, "a follow-up task page"
    (tmp_path / "e").mkdir()
    with _serve(tmp_path / "e", JOURNEY_SEED) as url:
        _home(page, url)
        _card(page, "Mangaroa Farm").get_by_role("button", name="Start trial", exact=True).click()
        expect(page.get_by_text("Builds this trial compares", exact=True)).to_be_visible(timeout=20_000)
        assert nav() == 0, "Set up"


# --- the Operator name ------------------------------------------------------------------------------------------------------

def test_the_operator_name_set_in_the_phone_menu_is_the_one_the_desktop_menu_shows(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        page.get_by_role("button", name="More", exact=True).click()
        box = page.get_by_role("dialog", name="More").get_by_role("textbox", name="Operator", exact=True)
        box.fill("Sam"); box.press("Enter"); page.wait_for_timeout(1_500)
        page.keyboard.press("Escape")
        page.set_viewport_size(DESKTOP); page.wait_for_timeout(800)
        page.get_by_role("button", name="Administration", exact=True).click()
        assert page.get_by_role("dialog", name="Administration").get_by_role("textbox", name="Operator", exact=True).input_value() == "Sam"


# --- back pills name where they go -------------------------------------------------------------------------------------------

def test_the_trial_periods_back_pill_uses_the_pages_current_name(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(DESKTOP)
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        page.get_by_role("button", name="Administration", exact=True).click()
        page.get_by_role("dialog", name="Administration").get_by_role("link", name="Data & records", exact=True).click()
        expect(page).to_have_url(re.compile(r"/data-records$"), timeout=20_000)
        page.get_by_role("radio", name="Trial history").check(force=True)
        expect(page.get_by_role("button", name="Open trial history")).to_be_visible(timeout=20_000)
        page.get_by_role("button", name="Open trial history").click()
        expect(page.get_by_role("button", name="← Back to Data & records")).to_be_visible(timeout=20_000)
        assert page.get_by_role("button", name=re.compile("Data Management")).count() == 0


# --- the Data quality count inside the phone's More menu ---------------------------------------------------------------------

from test_data_quality_badge_ui import two_flagged_checks_app  # noqa: E402,F401  (the existing fixture: two flagged checks)


def test_the_data_quality_count_shows_inside_the_more_menu_on_a_phone(page: Page, two_flagged_checks_app: str) -> None:
    import os  # noqa: PLC0415
    page.set_viewport_size(PHONE)
    page.goto(two_flagged_checks_app, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="More", exact=True).click()
    link = page.get_by_role("dialog", name="More").locator('a[href$="data-quality"]')
    expect(link).to_be_visible(timeout=15_000)
    badge = link.evaluate("el => getComputedStyle(el, '::after').content").strip('"')
    assert badge == "2", f"two flagged checks show a count of 2 beside Data quality in More, got {badge!r}"
    assert link.evaluate("el => el.getBoundingClientRect().height") >= 44, "the menu row is a 44px tap target"
    if os.environ.get("R1M1_NAV_SHOT_DIR"):
        page.wait_for_timeout(600)
        page.screenshot(path=os.path.join(os.environ["R1M1_NAV_SHOT_DIR"], "414_nav_14_more_menu_with_data_quality_count.png"), clip={"x": 0, "y": 0, "width": 414, "height": 700})
