from __future__ import annotations

import re
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import Page, expect

SHOTS = Path(__file__).resolve().parents[1] / "evidence" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)


def open_home(page: Page, local_app: dict, viewport: dict) -> None:
    page.set_viewport_size(viewport)
    page.goto(local_app["url"], wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)


def start_first_site(page: Page) -> None:
    page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
    page.screenshot(path=SHOTS / "mobile_partial_visit.png", full_page=True)


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
def test_home_renders_light_without_horizontal_overflow(page: Page, local_app: dict, viewport: dict, name: str) -> None:
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


def test_non_kill_check_returns_to_top_with_one_clear_checked_state(page: Page, local_app: dict) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})
    start_first_site(page)
    page.get_by_role("button", name="Check").nth(1).click()  # no-camera trap
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=20_000)
    assert main_scroll_top(page) <= 8

    page.get_by_role("radio", name="Trap still set, no animal").check()
    page.get_by_role("radio", name="Yes").first.check()
    page.get_by_role("button", name="Save check").click()

    expect(page.get_by_text(re.compile(r"saved$", re.I)).first).to_be_visible(timeout=30_000)
    expect(page.get_by_text("✓ Checked", exact=True)).to_be_visible(timeout=20_000)
    assert page.get_by_text("✓ Checked", exact=True).count() == 1
    assert main_scroll_top(page) <= 8
    page.screenshot(path=SHOTS / "mobile_checked_state.png", full_page=True)


def test_three_photo_kill_reports_three_stored(page: Page, local_app: dict, tmp_path: Path) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})
    start_first_site(page)
    page.get_by_role("button", name="Check").first.click()
    page.get_by_role("radio", name="Dead animal found").check()

    files=[]
    for i in range(3):
        path=tmp_path/f"photo_{i}.jpg"
        Image.new("RGB", (120+i, 100+i), (60+i*20, 100, 140)).save(path)
        files.append(str(path))
    page.locator('input[type="file"]').set_input_files(files)
    expect(page.get_by_text("3 photos ready to save", exact=True)).to_be_visible(timeout=30_000)
    page.screenshot(path=SHOTS / "mobile_photo_queue_ready.png", full_page=True)

    page.get_by_role("radio", name="Rat", exact=True).check()
    page.get_by_role("radio", name="Norway rat").check()
    page.get_by_role("radio", name="Dead and apparently normal").check()
    page.get_by_role("checkbox", name=re.compile(r"Bag labelled")).check()
    page.get_by_role("radio", name="Yes").first.check()  # trap service
    page.get_by_role("radio", name="Yes").last.check()   # camera check
    page.get_by_role("button", name="Save check").click()

    expect(page.get_by_text("3 photos stored", exact=True)).to_be_visible(timeout=60_000)
    page.screenshot(path=SHOTS / "mobile_photo_queue_processed.png", full_page=True)
    assert main_scroll_top(page) <= 8


def test_data_section_survives_table_change(page: Page, local_app: dict) -> None:
    open_home(page, local_app, {"width": 1440, "height": 1000})
    sidebar=page.get_by_test_id("stSidebar")
    sidebar.get_by_text("Administration", exact=True).click()
    sidebar.get_by_role("button", name="Data & records").click()
    expect(page.get_by_text("Data & records", exact=True).last).to_be_visible(timeout=20_000)
    page.get_by_role("radio", name="Export and backup").check()
    select=page.get_by_label("Inspect data table")
    select.select_option(label="Checks") if select.evaluate("el => el.tagName") == "SELECT" else None
    # BaseWeb select fallback.
    if page.get_by_text("Checks", exact=True).count() == 0:
        select.click(); page.get_by_role("option", name="Checks").click()
    expect(page.get_by_role("radio", name="Export and backup")).to_be_checked()
    page.screenshot(path=SHOTS / "desktop_data_records.png", full_page=True)


def test_navigation_labels_and_trap_detail(page: Page, local_app: dict) -> None:
    open_home(page, local_app, {"width": 1440, "height": 1000})
    sidebar=page.get_by_test_id("stSidebar")
    for label in ["Trap sites", "Traps", "Follow-ups", "Trial performance"]:
        expect(sidebar.get_by_text(label, exact=True)).to_be_visible(timeout=10_000)
    sidebar.get_by_role("button", name="Traps").click()
    expect(page.get_by_text("Traps", exact=True).last).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="View").first.click()
    expect(page.get_by_role("button", name=re.compile("Back to traps", re.I))).to_be_visible(timeout=20_000)
    assert main_scroll_top(page) <= 8



def test_all_traps_checked_completion_state(page: Page, local_app: dict) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})
    start_first_site(page)

    # Complete every trap in the current site against disposable data. This proves
    # progress, the all-checked state and the enabled primary completion action.
    for _ in range(30):
        check_buttons = page.get_by_role("button", name="Check")
        if check_buttons.count() == 0:
            break
        check_buttons.first.click()
        expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("radio", name="Trap still set, no animal").check()
        yes_options = page.get_by_role("radio", name="Yes")
        for index in range(yes_options.count()):
            option = yes_options.nth(index)
            if option.is_visible() and option.is_enabled():
                option.check()
        page.get_by_role("button", name="Save check").click()
        expect(page.get_by_text(re.compile(r"saved$", re.I)).first).to_be_visible(timeout=30_000)
    else:
        pytest.fail("Trap loop exceeded 30 checks; visit did not converge")

    all_checked = page.get_by_text(re.compile(r"All \d+ traps checked", re.I)).first
    expect(all_checked).to_be_visible(timeout=30_000)
    expect(page.get_by_role("button", name="Finish site check")).to_be_enabled()
    page.screenshot(path=SHOTS / "mobile_all_traps_checked.png", full_page=True)


def test_move_trap_section_stays_open_after_confirmation(page: Page, local_app: dict) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})
    sidebar = page.get_by_test_id("stSidebar")
    sidebar.get_by_text("Administration", exact=True).click()
    sidebar.get_by_role("button", name="Trial setup").click()
    expect(page.get_by_text("Trial setup", exact=True).last).to_be_visible(timeout=20_000)
    # Enter the first trap editor, then open Move trap. This is deliberately
    # a state-preservation assertion, not a destructive move action.
    page.get_by_role("button", name=re.compile(r"Edit", re.I)).first.click()
    move_toggle = page.get_by_text("Move trap", exact=True).first
    expect(move_toggle).to_be_visible(timeout=20_000)
    move_toggle.click()
    expect(page.get_by_text("Destination site", exact=True)).to_be_visible(timeout=20_000)
    confirmation = page.get_by_role("checkbox", name=re.compile(r"Close the current window|Move .* and start a new window", re.I))
    confirmation.check()
    # Checking the final confirmation causes a Streamlit rerun. The move section
    # must remain open and retain the destination controls after that rerun.
    expect(page.get_by_text("Destination site", exact=True)).to_be_visible(timeout=20_000)
    expect(confirmation).to_be_checked()
    page.screenshot(path=SHOTS / "mobile_move_trap_open.png", full_page=True)
