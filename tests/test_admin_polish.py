"""Layout fixes after the admin redesign went live (20 Oct 2026): the grey row cards keep their padding, the Data & records cards are one height, the Traps filters
sit on one line, a table cell never cuts its text short, and the saved-message panel is the page's width with a gap under it. Each was visible in the owner's
screenshots of the live app and in the 1280 captures of the PR; none had a test."""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).resolve().parent))
import admin_page as ap  # noqa: E402
from admin_seed import DQ_SEED  # noqa: E402
from test_admin_data import DESKTOP, PHONE, _open  # noqa: E402
from test_check_save_golden_ui import _serve  # noqa: E402

PADDING = '''(sel) => { const e = [...document.querySelectorAll(sel)].find(x => x.offsetParent); const s = getComputedStyle(e); const r = e.getBoundingClientRect();
    const b = e.querySelector("button"); const br = b ? b.getBoundingClientRect() : null;
    return {left: parseFloat(s.paddingLeft), right: parseFloat(s.paddingRight), bottomRule: s.borderBottomWidth, gapRight: br ? r.right - br.right : null, gapLeft: 0} }'''


def card_padding(page: Page, selector: str) -> dict:
    return page.evaluate(PADDING, selector)


def test_grey_row_cards_keep_their_padding_and_the_button_sits_inside_the_card(page: Page, tmp_path: Path) -> None:
    """The generic list-row rule used to zero every typed card's padding: the text and the button touched the card's edges, on a desktop and on a phone."""
    with _serve(tmp_path / "d", DQ_SEED) as url:
        for size in (DESKTOP, PHONE):
            page.set_viewport_size(size)
            _open(page, url, "Data & records")
            card = card_padding(page, '[class*="st-key-listrow_data_"]')
            assert card["left"] >= 16 and card["right"] >= 16 and card["bottomRule"] == "0px", (size, card)
            ap.go_to(page, "Traps")
            page.locator('[class*="st-key-listrow_net_R1-MAN-001"] button').first.click()
            expect(page.locator('[class*="st-key-listrow_net_task_"]').first).to_be_visible(timeout=30_000)
            task = card_padding(page, '[class*="st-key-listrow_net_task_"]')
            assert task["left"] >= 14 and task["right"] >= 14 and task["gapRight"] >= 12, (size, task)
            ap.go_to(page, "Data quality")
            expect(page.get_by_role("heading", name="Data quality review", exact=True)).to_be_visible(timeout=30_000)
            ap.go_to(page, "Trial setup")
            if size is PHONE:  # a phone shows the grey cards; a desktop shows the table (its own padding)
                setup = card_padding(page, '[class*="st-key-listrow_trap_"]')
                assert setup["left"] >= 14 and setup["gapRight"] >= 12, (size, setup)


def test_data_and_records_cards_are_one_height_on_a_desktop(page: Page, tmp_path: Path) -> None:
    with _serve(tmp_path / "d", DQ_SEED) as url:
        for width in (1000, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            _open(page, url, "Data & records")
            page.wait_for_timeout(800)
            for group in ("corrections", "review"):
                heights = {round(box["height"]) for box in (c.bounding_box() for c in page.locator(f'[class*="st-key-setup_trap_rows_{group}"] [class*="st-key-listrow_data_"]').all())}
                assert len(heights) == 1, f"{group} cards at {width}px are one height, not {sorted(heights)}"


def test_the_traps_filters_are_on_one_line_with_their_bottoms_level_and_stack_on_a_phone(page: Page, tmp_path: Path) -> None:
    with _serve(tmp_path / "d", DQ_SEED) as url:
        page.set_viewport_size({"width": 1440, "height": 900})
        _open(page, url, "Traps")
        page.wait_for_timeout(800)
        search = page.get_by_placeholder("Find a trap by ID or location").bounding_box()
        chips = page.locator('[class*="st-key-chips_traps_filter"] [role="radio"]').first.bounding_box()
        status = page.locator('[class*="st-key-seg_traps_status_wrap"] [role="radio"]').first.bounding_box()
        bottoms = [search["y"] + search["height"], chips["y"] + chips["height"], status["y"] + status["height"]]
        assert max(bottoms) - min(bottoms) <= 8, f"the search, the site chips and Status sit on one line, their bottoms level: {bottoms}"
        assert search["x"] < chips["x"] < status["x"], (search, chips, status)
        page.set_viewport_size(PHONE)
        page.wait_for_timeout(1_200)
        search, chips, status = (page.get_by_placeholder("Find a trap by ID or location").bounding_box(), page.locator('[class*="st-key-chips_traps_filter"] [role="radio"]').first.bounding_box(),
                                 page.locator('[class*="st-key-seg_traps_status_wrap"] [role="radio"]').first.bounding_box())
        assert search["y"] < chips["y"] < status["y"], "a phone stacks them: the search, the site chips, then Status"


def test_a_table_cell_wraps_and_is_never_cut_short(page: Page, tmp_path: Path) -> None:
    with _serve(tmp_path / "d", DQ_SEED) as url:
        for width in (800, 1000):
            page.set_viewport_size({"width": width, "height": 900})
            _open(page, url, "Traps")
            page.wait_for_timeout(800)
            cut = page.evaluate("""() => [...document.querySelectorAll('.r1-dk .c')].filter(e => e.offsetParent && (getComputedStyle(e).textOverflow === 'ellipsis' || e.scrollWidth > e.clientWidth + 1)).map(e => e.textContent.trim()).slice(0, 5)""")
            assert cut == [], f"at {width}px no cell is cut short: {cut}"
            card = page.locator('[class*="st-key-tablewrap_traps"]').bounding_box()
            view = page.locator('[class*="st-key-listrow_net_R1-MAN-001"] button').first.bounding_box()
            assert view["x"] + view["width"] <= card["x"] + card["width"] + 1, f"the View button stays inside the card at {width}px"


def test_the_saved_message_is_as_wide_as_the_page_with_a_gap_under_it(page: Page, tmp_path: Path) -> None:
    """Confirming the last flagged check leaves one 760 column with "Nothing is waiting"; the "Confirmed as real." panel above it used to be the full 1160 and sat on the title."""
    with _serve(tmp_path / "d", DQ_SEED) as url:
        page.set_viewport_size(DESKTOP)
        _open(page, url, "Data quality")
        for check in ("CHK-DQ-1", "CHK-DQ-2"):
            page.locator(f'[class*="st-key-listrow_net_dq_{check}"] button').click()
            page.get_by_role("button", name="Confirm as real", exact=True).click()
            page.wait_for_timeout(1_500)
        expect(page.get_by_text("Nothing is waiting", exact=True)).to_be_visible(timeout=30_000)
        flash, screen = page.locator('[class*="st-key-flash_message"]').first.bounding_box(), page.locator(".st-key-r1_screen").first.bounding_box()
        title = page.get_by_role("heading", name="Data quality review", exact=True).bounding_box()
        assert flash["width"] <= 761 and abs(flash["width"] - screen["width"]) <= 2 and abs(flash["x"] - screen["x"]) <= 1, (flash, screen)
        assert title["y"] - (flash["y"] + flash["height"]) >= 12, f"a gap under the message: {title['y'] - (flash['y'] + flash['height'])}"
