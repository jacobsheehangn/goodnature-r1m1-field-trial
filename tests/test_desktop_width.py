"""Desktop page width (14 Oct 2026, boards FollowupsDesktop, VisitCompleteDesktop, TrialHubDesktop; note n-width).

The old 1020px page cap is gone: desktop pages use up to 1160px of content. Single-column screens keep a 760px column, left-aligned (Follow-ups
list, task forms); multi-column screens use the full width (Trap sites grid, trial hub, Visit complete, Trial performance). The phone is unchanged.
Also held: the highlighted next row on Follow-ups lines up with the other rows, the hub puts End trial under the Visits card, Visit complete is one
compact card on desktop and the same centred summary on a phone, the site card's number is top-aligned on desktop and the tag is 13px."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).resolve().parent))
from journey_seed import END_SEED  # noqa: E402
from test_trap_sites_desktop import seed as sites_seed, serve  # noqa: E402

COMPLETE_VISIT = """
    import app, pandas as pd
    d = app.load_data()
    v = d["Visits"][(d["Visits"]["Site ID"] == "MAN") & (d["Visits"]["Status"] == "In progress")].iloc[-1]["Visit ID"]
    done = set(d["Checks"][d["Checks"]["Visit ID"] == v]["Trap ID"].astype(str))
    for trap in d["Traps"][(d["Traps"]["Site ID"] == "MAN") & (d["Traps"]["Status"] == "Active")]["Trap ID"].tolist():
        if trap in done: continue
        w = d["Windows"][(d["Windows"]["Trap ID"] == trap) & (d["Windows"]["Status"] == "Open")].iloc[-1]
        row = [app.make_id("CHK"), v, trap, w["Window ID"], app.dtstr(app.now()), "Trap still set, no animal", "", "", "", "", "No", "No", "", "Yes", "Yes", "Yes", "Ready", "Ready after service", "", "No camera", "Not applicable", "No", "", "", "", ""]
        d["Checks"] = pd.concat([d["Checks"], pd.DataFrame([row], columns=app.SHEETS["Checks"])], ignore_index=True)
    app.save_data(d)
"""
END_ALL_CHECKED = textwrap.dedent(END_SEED) + "\n" + textwrap.dedent(COMPLETE_VISIT)


def open_home(page: Page, url: str, width: int, height: int = 1100) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url, wait_until="domcontentloaded")
    page.locator(".r1-title").first.wait_for(timeout=45000)
    page.wait_for_timeout(1500)


def box(page: Page, selector: str) -> dict:
    return page.locator(selector).first.bounding_box()


@pytest.mark.parametrize("width", [1280, 1440, 1920])
def test_a_multi_column_screen_uses_1160_of_content(width, tmp_path, page: Page):
    with serve(tmp_path / "d", sites_seed()) as url:
        open_home(page, url, width)
        screen = box(page, ".st-key-r1_screen")
        assert abs(screen["width"] - 1160) <= 2, f"Trap sites at {width}: {screen}"
        nav = box(page, ".st-key-app_nav")
        assert abs(nav["x"] - screen["x"]) <= 1, "the navigation lines up with the page content"


def test_the_phone_is_unchanged(tmp_path, page: Page):
    with serve(tmp_path / "d", sites_seed()) as url:
        open_home(page, url, 390, 1700)
        screen = box(page, ".st-key-r1_screen")
        assert screen["x"] <= 16 and screen["width"] >= 390 - 32, screen


def test_follow_ups_is_a_760_column_left_aligned_and_the_next_row_lines_up(tmp_path, page: Page):
    with serve(tmp_path / "d", END_SEED) as url:
        open_home(page, url, 1280)
        page.get_by_role("link", name="Follow-ups").first.click()
        page.locator(".r1-title", has_text="Follow-ups").first.wait_for(timeout=30000)
        page.wait_for_timeout(1500)
        screen = box(page, ".st-key-r1_screen")
        nav = box(page, ".st-key-app_nav")
        assert screen["width"] <= 761 and abs(screen["x"] - nav["x"]) <= 1, f"a 760 column at the page's left edge: {screen} {nav}"
        icons = page.locator('[class*="st-key-listrow_"] .r1-rowicon').all()
        buttons = page.locator('[class*="st-key-listrow_"] button').all()
        assert len(icons) >= 3 and len(buttons) >= 3
        lefts = {round(i.bounding_box()["x"]) for i in icons}
        rights = {round(b.bounding_box()["x"] + b.bounding_box()["width"]) for b in buttons if b.inner_text().strip() == "Review"}
        assert len(lefts) == 1, f"every row's icon sits at the same x, the highlighted next row's included: {lefts}"
        assert len(rights) == 1, f"every Review button ends at the same x: {rights}"


def test_a_task_form_is_a_760_column(tmp_path, page: Page):
    with serve(tmp_path / "d", END_SEED) as url:
        open_home(page, url, 1280)
        page.get_by_role("link", name="Follow-ups").first.click()
        page.locator(".r1-title", has_text="Follow-ups").first.wait_for(timeout=30000)
        page.get_by_role("button", name="Review", exact=True).nth(1).click()  # the Camera issue task (legacy form)
        page.wait_for_timeout(2500)
        widths = page.evaluate("""() => [...document.querySelectorAll('[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > *')]
            .filter(e => !e.className.includes('st-key-app_nav') && e.getBoundingClientRect().width > 0).map(e => Math.round(e.getBoundingClientRect().width))""")
        assert widths and max(widths) <= 761, widths


def test_the_hub_puts_end_trial_under_the_visits_card_in_the_left_column(tmp_path, page: Page):
    with serve(tmp_path / "d", END_ALL_CHECKED) as url:
        open_home(page, url, 1280)
        page.get_by_role("button", name="Trial overview").first.click()
        page.get_by_text("Evidence waiting").first.wait_for(timeout=30000)
        page.wait_for_timeout(1000)
        visits, evidence = box(page, '[class*="st-key-card_hub_visits"]'), box(page, '[class*="st-key-card_hub_evidence"]')
        end = page.get_by_role("button", name="End trial…").first.bounding_box()
        assert end["x"] < visits["x"] + visits["width"] and end["y"] > visits["y"] + visits["height"], "End trial is under the Visits card"
        assert end["x"] < evidence["x"], "and in the left column, not under the right card"
        assert abs(visits["width"] / evidence["width"] - 1.65) < 0.2, f"columns are 1.65 : 1 ({visits['width']} / {evidence['width']})"
        assert page.locator("hr").count() == 0, "no divider"


def test_visit_complete_is_one_compact_card_on_desktop_and_unchanged_on_a_phone(tmp_path, page: Page):
    with serve(tmp_path / "d", END_ALL_CHECKED) as url:
        open_home(page, url, 1280)
        page.get_by_role("button", name="Resume checking").first.click()
        page.get_by_role("button", name="Finish site check").click()
        page.locator(".r1-vc").wait_for(timeout=30000)
        page.wait_for_timeout(800)
        card, title, stats = box(page, ".r1-vc"), box(page, ".r1-vc-title"), box(page, ".r1-vc-stats")
        assert abs(card["width"] - 1160) <= 2 and card["height"] < 130, f"one compact card across the top: {card}"
        assert title["x"] < card["x"] + card["width"] / 2 < stats["x"], "the title at the left, the counts at the right"
        assert "next visit due" in page.locator(".r1-vc-site").inner_text()
        assert not page.locator(".r1-vc-next").is_visible()
        page.set_viewport_size({"width": 390, "height": 1700})
        page.wait_for_timeout(800)
        assert not page.locator(".r1-vc-site .dk").is_visible() and page.locator(".r1-vc-next").is_visible()
        assert page.locator(".r1-vc").evaluate("e => getComputedStyle(e).textAlign") == "center"


def test_the_site_cards_number_is_top_aligned_on_desktop_only_and_the_tag_is_13px(tmp_path, page: Page):
    with serve(tmp_path / "d", sites_seed()) as url:
        open_home(page, url, 1280)
        name, stat = box(page, '[class*="st-key-card_site_MAN"] .r1-card-title'), box(page, '[class*="st-key-card_site_MAN"] .r1-stat')
        assert abs(stat["y"] - name["y"]) <= 8, f"the number is top-aligned with the name on desktop: {name} {stat}"
        assert page.locator(".r1-tag").first.evaluate("e => getComputedStyle(e).fontSize") == "13px"
        page.set_viewport_size({"width": 390, "height": 1700})
        page.wait_for_timeout(800)
        name, stat = box(page, '[class*="st-key-card_site_MAN"] .r1-card-title'), box(page, '[class*="st-key-card_site_MAN"] .r1-stat')
        assert stat["y"] > name["y"] + 4, "on a phone the number keeps its place (not top-aligned)"
