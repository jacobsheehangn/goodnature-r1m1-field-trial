from __future__ import annotations

import re
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "evidence" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)


def open_home(page: Page, local_app: str, viewport: dict) -> None:
    page.set_viewport_size(viewport)
    page.goto(local_app, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)


def start_first_site(page: Page) -> None:
    page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)


def main_scroll_top(page: Page) -> int:
    return int(page.evaluate("""() => {
      const el = document.querySelector('[data-testid="stMainScrollContainer"]')
        || document.querySelector('[data-testid="stAppViewContainer"] .main')
        || document.scrollingElement;
      return Math.round(el ? el.scrollTop : window.scrollY);
    }"""))


@pytest.mark.parametrize("viewport,name", [
    ({"width": 390, "height": 844}, "mobile_390"),
    ({"width": 430, "height": 932}, "mobile_430"),
    ({"width": 1440, "height": 1000}, "desktop_1440"),
])
def test_home_renders_light_without_horizontal_overflow(page: Page, local_app: str, viewport: dict, name: str) -> None:
    open_home(page, local_app, viewport)
    page.screenshot(path=SHOTS / f"{name}_home.png", full_page=True)
    overflow = page.evaluate("() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2")
    assert overflow is False
    colors = page.evaluate("""() => ({
      body: getComputedStyle(document.body).backgroundColor,
      app: getComputedStyle(document.querySelector('[data-testid="stAppViewContainer"]')).backgroundColor
    })""")
    assert colors["body"] in {"rgb(255, 255, 255)", "rgba(0, 0, 0, 0)"}
    assert colors["app"] == "rgb(255, 255, 255)"


def test_non_kill_check_returns_to_top_with_one_clear_checked_state(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})
    start_first_site(page)
    page.get_by_role("button", name="Check", exact=True).nth(2).click()  # no-camera trap
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=20_000)
    assert main_scroll_top(page) <= 8

    page.get_by_role("radio", name="Trap still set, no animal").check(force=True)
    page.get_by_role("radio", name="Yes").first.check(force=True)
    page.get_by_role("button", name="Save check").click()

    expect(page.get_by_text(re.compile(r"saved$", re.I)).first).to_be_visible(timeout=30_000)
    expect(page.get_by_text("✓ Checked", exact=True)).to_be_visible(timeout=20_000)
    assert page.get_by_text("✓ Checked", exact=True).count() == 1
    assert main_scroll_top(page) <= 8
    page.screenshot(path=SHOTS / "mobile_checked_state.png", full_page=True)


def test_three_photo_kill_reports_three_stored(page: Page, local_app: str, tmp_path: Path) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})
    start_first_site(page)
    page.get_by_role("button", name="Check", exact=True).nth(1).click()  # camera-equipped trap
    page.get_by_role("radio", name="Dead animal found").check(force=True)

    files=[]
    for i in range(3):
        path=tmp_path/f"photo_{i}.jpg"
        Image.new("RGB", (120+i, 100+i), (60+i*20, 100, 140)).save(path)
        files.append(str(path))
    photo_frame = page.frame_locator('iframe[title="app.r1m1_photo_upload"]')
    photo_frame.locator('input[type="file"]').set_input_files(files)
    photo_queue_ready = page.get_by_text("3 photos saved", exact=True)
    expect(photo_queue_ready).to_be_visible(timeout=30_000)
    photo_queue_ready.scroll_into_view_if_needed()
    page.screenshot(path=SHOTS / "mobile_photo_queue_ready.png", full_page=True)

    page.get_by_role("radio", name="Rat", exact=True).check(force=True)
    page.get_by_role("radio", name="Norway rat").check(force=True)
    page.get_by_role("radio", name="Dead and apparently normal").check(force=True)
    page.get_by_role("checkbox", name=re.compile(r"Bag labelled")).evaluate("el => el.click()")
    page.get_by_role("radio", name="Yes").first.check(force=True)  # trap service
    page.get_by_role("radio", name="Yes").last.check(force=True)   # camera check
    page.get_by_role("button", name="Save check").click()

    photo_queue_processed = page.get_by_text("3 photos stored", exact=True)
    expect(photo_queue_processed).to_be_visible(timeout=60_000)
    assert main_scroll_top(page) <= 8
    photo_queue_processed.scroll_into_view_if_needed()
    page.screenshot(path=SHOTS / "mobile_photo_queue_processed.png", full_page=True)


def test_data_section_survives_table_change(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 1440, "height": 1000})
    page.get_by_role("button", name="Administration", exact=True).click()
    page.get_by_role("dialog", name="Administration").get_by_role("link", name="Data & records", exact=True).click()
    expect(page.get_by_text("Data & records", exact=True).last).to_be_visible(timeout=20_000)
    page.get_by_role("radio", name="Export and backup").check(force=True)
    select=page.get_by_label("Inspect data table")
    select.select_option(label="Checks") if select.evaluate("el => el.tagName") == "SELECT" else None
    # BaseWeb select fallback.
    if page.get_by_text("Checks", exact=True).count() == 0:
        select.click(); page.get_by_role("option", name="Checks").click()
    expect(page.get_by_role("radio", name="Export and backup")).to_be_checked()
    expect(page.get_by_text("Export is read-only. Opening this page does not change trial data.", exact=True)).to_be_visible(timeout=20_000)
    page.screenshot(path=SHOTS / "desktop_data_records.png", full_page=True)


def test_navigation_labels_and_trap_detail(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 1440, "height": 1000})
    for label in ["Trap sites", "Traps", "Follow-ups", "Trial performance"]:
        expect(page.get_by_role("link", name=label, exact=True)).to_be_visible(timeout=10_000)
    page.get_by_role("link", name="Traps", exact=True).click()
    expect(page.get_by_text("Traps", exact=True).last).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="View").first.click()
    expect(page.get_by_role("button", name=re.compile("Back to traps", re.I))).to_be_visible(timeout=20_000)
    assert main_scroll_top(page) <= 8


def test_all_traps_checked_shows_completion(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})
    start_first_site(page)

    captured_partial = False
    for _ in range(10):
        if page.get_by_text(re.compile(r"^All \d+ traps checked$")).count():
            break
        # The visit page re-renders its trap cards after each save; wait for the
        # progress line so we never sample the Check buttons mid-render.
        expect(page.get_by_text(re.compile(r"^\d+ of \d+ traps checked$"))).to_be_visible(timeout=20_000)
        check_buttons = page.get_by_role("button", name="Check", exact=True)
        expect(check_buttons.first).to_be_visible(timeout=20_000)
        check_buttons.first.click()
        expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("radio", name="Trap still set, no animal").check(force=True)
        expect(page.get_by_text("Trap service", exact=True)).to_be_visible(timeout=20_000)
        has_camera_step = page.get_by_text("Camera working and covering the trap?", exact=True).count() > 0

        page.get_by_role("radio", name="Yes").first.check(force=True)  # trap service ready
        if has_camera_step:
            page.get_by_role("radio", name="Yes").last.check(force=True)  # camera working
        page.get_by_role("button", name="Save check").click()
        expect(page.get_by_text(re.compile(r"saved$", re.I)).first).to_be_visible(timeout=30_000)

        if not captured_partial:
            expect(page.get_by_text(re.compile(r"^\d+ of \d+ traps checked$"))).to_be_visible(timeout=20_000)
            page.screenshot(path=SHOTS / "mobile_partial_visit.png", full_page=True)
            captured_partial = True
    else:
        pytest.fail("Did not reach an all-traps-checked state within 10 checks.")

    expect(page.get_by_text(re.compile(r"^All \d+ traps checked$"))).to_be_visible(timeout=20_000)
    page.screenshot(path=SHOTS / "mobile_all_traps_checked.png", full_page=True)


def test_move_trap_panel_opens_from_trial_setup(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})
    page.get_by_role("button", name="Administration", exact=True).click()
    page.get_by_role("dialog", name="Administration").get_by_role("link", name="Trial setup", exact=True).click()
    expect(page.get_by_text("Trial setup", exact=True).last).to_be_visible(timeout=20_000)

    page.get_by_role("button", name="Edit", exact=True).first.click()
    expect(page.get_by_role("switch", name="Move trap")).to_be_visible(timeout=20_000)
    page.get_by_role("switch", name="Move trap").evaluate("el => el.click()")
    destination_site = page.get_by_text("Destination site", exact=True)
    expect(destination_site).to_be_visible(timeout=20_000)
    destination_site.scroll_into_view_if_needed()
    page.screenshot(path=SHOTS / "mobile_move_trap_open.png", full_page=True)
