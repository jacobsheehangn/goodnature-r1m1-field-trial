"""Part B batch 2b: the Traps list and a trap's history (boards AdmTrapsList, AdmTrapsPhone, AdmTrapHistory), Trial periods (AdmPeriods), Data & records (AdmDataRecords,
AdmDataRecordsPhone) and the one-column width the admin pages keep (760 on a desktop). Read-only screens: nothing here writes. Local test data only."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
import admin_page as ap  # noqa: E402
from admin_seed import ADMIN_SEED  # noqa: E402
from test_check_save_golden_ui import _serve  # noqa: E402
from test_trial_model_ui import _sheet  # noqa: E402

DESKTOP, PHONE = {"width": 1280, "height": 900}, {"width": 390, "height": 844}
DATA_PAGES = ["Camera evidence", "Necropsy evidence", "Field check", "Follow-up task", "Incomplete visit", "Kill with no carcass", "Stray window on an Inactive trap",
              "Window start corrections", "Trial periods", "Audit log", "Export and backup"]


def _open(page: Page, url: str, item: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    ap.go_to(page, item)


def _rows(page: Page, prefix: str):
    return page.locator(f'[class*="st-key-{prefix}"]')


def test_the_traps_list_filters_by_status_and_search_and_says_so_when_nothing_matches(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size(DESKTOP)
    d = tmp_path / "d"
    with _serve(d, ADMIN_SEED) as url:
        _open(page, url, "Traps")
        expect(page.get_by_role("heading", name="Traps", exact=True)).to_be_visible(timeout=30_000)
        everything = _rows(page, "listrow_net_").count()
        assert everything >= 8, "every trap, with its record so far"
        page.get_by_role("radio", name="Inactive", exact=True).click()
        page.wait_for_timeout(1_200)
        inactive = _rows(page, "listrow_net_")
        traps = _sheet(d, "Traps")
        assert inactive.count() == (traps["Status"] == "Inactive").sum() >= 2, "R1-MAN-005 (deactivated) and R1-MAN-NEW1 (never activated) among them"
        assert all("Inactive" in text for text in inactive.all_inner_texts())
        page.get_by_role("radio", name="Active", exact=True).click()
        page.wait_for_timeout(1_200)
        assert _rows(page, "listrow_net_").count() == (traps["Status"] == "Active").sum()
        page.get_by_role("radio", name="All", exact=True).click()
        page.wait_for_timeout(1_200)
        page.get_by_placeholder("Find a trap by ID or location").fill("NEW1")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1_200)
        assert _rows(page, "listrow_net_").count() == 1
        page.get_by_placeholder("Find a trap by ID or location").fill("no such trap")
        page.keyboard.press("Enter")
        expect(page.get_by_text("No traps match this filter", exact=True)).to_be_visible(timeout=15_000)
        expect(page.get_by_text("Change the site or status to see more.", exact=True)).to_be_visible()


def test_a_trap_history_has_three_counts_the_open_tasks_above_the_timeline_and_a_way_back(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size(DESKTOP)
    d = tmp_path / "d"
    with _serve(d, ADMIN_SEED) as url:
        tasks = _sheet(d, "Followups")
        task = tasks[tasks["Status"] == "Open"].iloc[0]
        trap = str(task["Trap ID"])
        _open(page, url, "Traps")
        page.locator(f'.st-key-listrow_net_{trap} button').click()
        expect(page.get_by_role("heading", name=trap, exact=True)).to_be_visible(timeout=30_000)
        assert page.locator(".r1-statcard span").all_inner_texts() == ["Kills", "Checks", "Last kill"]
        assert page.get_by_text("Open tasks", exact=True).count() == 1 and page.get_by_text("Full history", exact=True).count() == 1
        open_y = page.get_by_text("Open tasks", exact=True).bounding_box()["y"]
        full_y = page.get_by_text("Full history", exact=True).bounding_box()["y"]
        assert open_y < full_y, "the open tasks come above the timeline"
        review = page.locator('[class*="st-key-listrow_net_task_"]').first.get_by_role("button", name="Review", exact=True)
        review.click()
        expect(page.locator(".r1-title").filter(has_text=str(task["Follow-up Type"])).first).to_be_visible(timeout=30_000)

        # the way back from a history is the list
        page.go_back()
        _open(page, url, "Traps")
        page.locator(f'.st-key-listrow_net_{trap} button').click()
        expect(page.get_by_role("heading", name=trap, exact=True)).to_be_visible(timeout=30_000)
        page.get_by_role("button", name="Back to traps", exact=True).click()
        expect(page.get_by_role("heading", name="Traps", exact=True)).to_be_visible(timeout=30_000)


def test_trial_periods_lists_closed_windows_and_opens_one_beside_the_list(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size(DESKTOP)
    d = tmp_path / "d"
    with _serve(d, ADMIN_SEED) as url:
        windows = _sheet(d, "Windows")
        closed = windows[windows["Status"] == "Closed"]
        _open(page, url, "Data & records")
        page.get_by_role("button", name="Trial periods", exact=True).click()
        expect(page.get_by_role("heading", name="Trial periods", exact=True)).to_be_visible(timeout=30_000)
        page.wait_for_timeout(800)
        assert _rows(page, "listrow_win_").count() == len(closed), "Closed is the first view"
        page.get_by_role("radio", name="All", exact=True).click()
        page.wait_for_timeout(1_200)
        assert _rows(page, "listrow_win_").count() == len(windows)
        first_id = str(closed.sort_values("Start Time", ascending=False).iloc[0]["Window ID"])
        page.locator(f'[class*="st-key-listrow_win_{first_id}"] button').click()
        page.wait_for_timeout(1_200)
        panel = page.locator('[class*="st-key-card_setup_panel"]')
        expect(panel.get_by_text(first_id, exact=True)).to_be_visible(timeout=15_000)
        assert _rows(page, "listrow_win_").count() == len(windows), "the list stays beside the panel on a desktop"
        page.locator(".st-key-close_window_panel button").first.click()
        page.wait_for_timeout(1_200)
        assert page.locator('[class*="st-key-card_setup_panel"]').count() == 0

        # a phone shows the window as its own screen, with a way back to the list
        page.set_viewport_size(PHONE)
        page.wait_for_timeout(800)
        page.locator(f'[class*="st-key-listrow_win_{first_id}"] button').click()
        expect(page.get_by_role("button", name="Back to Trial periods", exact=True)).to_be_visible(timeout=15_000)
        assert _rows(page, "listrow_win_").first.is_hidden() or not _rows(page, "listrow_win_").first.is_visible()
        page.get_by_role("button", name="Back to Trial periods", exact=True).click()
        page.wait_for_timeout(1_200)
        assert _rows(page, "listrow_win_").first.is_visible()


def test_data_and_records_lists_every_page_and_each_one_opens_with_a_way_back(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size(DESKTOP)
    with _serve(tmp_path / "d", ADMIN_SEED) as url:
        _open(page, url, "Data & records")
        expect(page.get_by_role("heading", name="Data & records", exact=True)).to_be_visible(timeout=30_000)
        assert page.get_by_text("Correct a record", exact=True).count() == 1 and page.get_by_text("Review and export", exact=True).count() == 1
        for title in DATA_PAGES:
            page.get_by_role("button", name=title, exact=True).click()
            expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible(timeout=30_000)
            page.get_by_role("button", name="Back to Data & records", exact=True).click()
            expect(page.get_by_role("heading", name="Data & records", exact=True)).to_be_visible(timeout=30_000)


def test_lists_use_the_full_width_and_forms_stay_a_760_column_left_aligned_with_the_page(page: Page, tmp_path: Path) -> None:
    """The width rule (20 Oct): lists are the full 1160; a form, an action and a detail page are one 760px column."""
    page.set_viewport_size(DESKTOP)
    with _serve(tmp_path / "d", DQ_SEED) as url:
        seen = {}

        def measure(label: str, full: bool) -> None:
            page.wait_for_timeout(900)
            screen, nav = page.locator(".st-key-r1_screen").first.bounding_box(), page.locator(".st-key-app_nav").first.bounding_box()
            seen[label] = screen["width"]
            if full:
                assert abs(screen["width"] - 1160) <= 2, f"{label}: the full content width, not {screen['width']}"
            else:
                assert screen["width"] <= 761, f"{label}: one 760px column, not {screen['width']}"
            assert abs(screen["x"] - nav["x"]) <= 1, f"{label}: left-aligned with the page, not centred"

        _open(page, url, "Traps")
        measure("Traps list", True)
        page.locator('[class*="st-key-listrow_net_"] button').first.click()
        expect(page.locator(".r1-stats3")).to_be_visible(timeout=30_000)
        measure("Trap history", False)
        ap.go_to(page, "Data & records")
        measure("Data & records", True)
        page.get_by_role("button", name="Field check", exact=True).click()
        expect(page.get_by_role("heading", name="Field check", exact=True)).to_be_visible(timeout=30_000)
        measure("A correction page", False)
        ap.go_to(page, "Data & records")
        page.get_by_role("button", name="Audit log", exact=True).click()
        expect(page.get_by_role("heading", name="Audit log", exact=True)).to_be_visible(timeout=30_000)
        measure("Audit log", True)
        ap.go_to(page, "Data quality")
        expect(page.get_by_role("heading", name="Data quality review", exact=True)).to_be_visible(timeout=30_000)
        measure("Data quality list", True)
        page.locator('[class*="st-key-listrow_net_dq_"] button').first.click()
        page.wait_for_timeout(1_500)
        measure("Data quality review of one check", False)
        ap.go_to(page, "Trial setup")
        measure("Trial setup traps (no panel open)", True)
        page.get_by_role("radio", name="Trap sites", exact=True).click()
        page.wait_for_timeout(1_200)
        measure("Trial setup sites", True)
        page.get_by_role("radio", name="Builds", exact=True).click()
        page.wait_for_timeout(1_200)
        measure("Trial setup builds", True)
        ap.open_trap(page, url, "R1-MAN-NEW1")
        ap.action(page, "Activate", "Activate R1-MAN-NEW1")
        measure("A trap action page", False)
        assert len(seen) == 11


def test_a_list_is_a_table_on_a_desktop_and_stacked_rows_on_a_phone(page: Page, tmp_path: Path) -> None:
    """Traps, the Trial setup lists and the Data quality list: a header and a column per fact over 700px; the approved stacked rows on a phone; the compact rows beside a panel."""
    with _serve(tmp_path / "d", DQ_SEED) as url:
        page.set_viewport_size(DESKTOP)
        _open(page, url, "Traps")
        assert [h for h in page.locator(".r1-thead:visible").first.inner_text().split("\n") if h.strip()] == ["Trap", "Site", "Location", "Build", "Camera", "Kills", "Checks", "Last kill"]
        cells = page.locator('[class*="st-key-listrow_net_R1-MAN-001"] .r1-dk:visible .c').all_inner_texts()
        assert cells[0].startswith("R1-MAN-001") and cells[1] == "Mangaroa Farm" and cells[3] == "4.3" and cells[4] == "CAM-001", cells
        page.set_viewport_size(PHONE)
        page.wait_for_timeout(1_200)
        assert page.locator(".r1-thead:visible").count() == 0
        assert "Mangaroa Farm" in page.locator('[class*="st-key-listrow_net_R1-MAN-001"] .r1-mb:visible').first.inner_text()

        page.set_viewport_size(DESKTOP)
        ap.go_to(page, "Trial setup")
        assert [h for h in page.locator(".r1-thead:visible").first.inner_text().split("\n") if h.strip()] == ["Trap", "Site", "Location", "Build", "Camera", "Route"]
        # beside an open panel the list is the compact two-line rows
        page.get_by_role("button", name="Add trap", exact=True).first.click()
        expect(page.get_by_text("The permanent physical ID, without a site code.", exact=True)).to_be_visible(timeout=15_000)
        assert page.locator(".r1-thead:visible").count() == 0
        compact = page.locator('[class*="st-key-listrow_trap_R1-MAN-001"]').first
        assert compact.locator(".r1-row-title").is_visible() and compact.locator(".r1-dk:visible").count() == 0 and "Build 4.3" in compact.inner_text(), compact.inner_text()


def test_data_and_records_shows_its_two_groups_side_by_side_on_a_desktop_and_stacked_on_a_phone(page: Page, tmp_path: Path) -> None:
    """The width rule (20 Oct): "Correct a record" (two columns of rows) and "Review and export" sit side by side over 700px; a phone stacks them as before."""
    with _serve(tmp_path / "d", DQ_SEED) as url:
        page.set_viewport_size(DESKTOP)
        _open(page, url, "Data & records")
        correct, review = page.get_by_text("Correct a record", exact=True).bounding_box(), page.get_by_text("Review and export", exact=True).bounding_box()
        assert abs(correct["y"] - review["y"]) < 4 and review["x"] > correct["x"] + 400, (correct, review)
        rows = page.locator('[class*="st-key-setup_trap_rows_corrections"] [class*="st-key-listrow_data_"]')
        first, second = rows.nth(0).bounding_box(), rows.nth(1).bounding_box()
        assert abs(first["y"] - second["y"]) < 4 and second["x"] > first["x"] + 200, "the corrections are two columns of rows"
        for row in (rows.nth(0), page.locator('[class*="st-key-setup_trap_rows_review"] [class*="st-key-listrow_data_"]').first):
            assert row.locator("button").is_visible()
        page.set_viewport_size(PHONE)
        page.wait_for_timeout(1_200)
        correct, review = page.get_by_text("Correct a record", exact=True).bounding_box(), page.get_by_text("Review and export", exact=True).bounding_box()
        assert review["y"] > correct["y"] + 200 and abs(review["x"] - correct["x"]) < 4, "a phone stacks the groups"
        first, second = rows.nth(0).bounding_box(), rows.nth(1).bounding_box()
        assert second["y"] > first["y"] + 20 and abs(first["x"] - second["x"]) < 4, "and the rows are one column"


def test_the_data_quality_list_is_a_table_on_a_desktop_with_review_at_the_row_end(page: Page, tmp_path: Path) -> None:
    with _serve(tmp_path / "d", DQ_SEED) as url:
        page.set_viewport_size(DESKTOP)
        _open(page, url, "Data quality")
        expect(page.get_by_role("heading", name="Data quality review", exact=True)).to_be_visible(timeout=30_000)
        header = [h for h in page.locator(".r1-thead:visible").first.inner_text().split("\n") if h.strip()]
        assert header == ["Trap", "Site", "Checked", "Why it is flagged"], header
        buttons = page.locator('[class*="st-key-listrow_net_dq_"] button')
        assert buttons.count() == 2
        rights = {round(b.bounding_box()["x"] + b.bounding_box()["width"]) for b in buttons.all()}
        assert len(rights) == 1, f"the Review buttons end at the same x: {rights}"
        page.set_viewport_size(PHONE)
        page.wait_for_timeout(1_200)
        assert page.locator(".r1-thead:visible").count() == 0


# ---------------------------------------------------------------- Data quality (AdmDQList, AdmDQReview, AdmDQEmpty)

from admin_seed import DQ_SEED  # noqa: E402


def _flagged(page: Page, url: str) -> None:
    _open(page, url, "Data quality")
    expect(page.get_by_role("heading", name="Data quality review", exact=True)).to_be_visible(timeout=30_000)


def test_data_quality_lists_the_flagged_checks_and_opens_one_with_what_was_found_nearby(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size(DESKTOP)
    with _serve(tmp_path / "d", DQ_SEED) as url:
        _flagged(page, url)
        assert _rows(page, "listrow_net_dq_").count() == 2
        page.locator('[class*="st-key-listrow_net_dq_CHK-DQ-1"] button').click()
        expect(page.get_by_role("heading", name="R1-KAI-001", exact=True)).to_be_visible(timeout=30_000)
        assert re.search(r"reviewing \d of 2", page.locator(".r1-meta").first.inner_text())
        expect(page.locator(".r1-msg.warn").filter(has_text="No other activity at")).to_be_visible()
        page.get_by_role("button", name="Back to Data quality", exact=True).click()
        expect(_rows(page, "listrow_net_dq_")).to_have_count(2, timeout=15_000)


def test_voiding_needs_a_reason_and_confirming_does_not_change_the_record(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size(DESKTOP)
    d = tmp_path / "d"
    with _serve(d, DQ_SEED) as url:
        _flagged(page, url)
        page.locator('[class*="st-key-listrow_net_dq_CHK-DQ-1"] button').click()
        expect(page.get_by_role("heading", name="R1-KAI-001", exact=True)).to_be_visible(timeout=30_000)
        audit_before = len(_sheet(d, "Audit Log"))
        # refused: no reason, so the field is ringed, a line says why, and nothing is written
        page.get_by_role("button", name="Void as test data", exact=True).click()
        expect(page.get_by_text("Say why this is test data.", exact=True)).to_be_visible(timeout=15_000)
        assert page.locator('[class*="st-key-fielderr_reason_dq_"]').count() == 1
        checks = _sheet(d, "Checks")
        assert checks[checks["Check ID"] == "CHK-DQ-1"].iloc[0]["Excluded"] != "Yes" and len(_sheet(d, "Audit Log")) == audit_before

        # confirmed as real: the audit row is the only change, and the check is not flagged again
        page.get_by_role("button", name="Confirm as real", exact=True).click()
        expect(page.get_by_text("Confirmed as real.", exact=True)).to_be_visible(timeout=30_000)
        audit = _sheet(d, "Audit Log")
        assert len(audit) == audit_before + 1 and audit.iloc[-1]["Record ID"] == "CHK-DQ-1" and audit.iloc[-1]["New Value"] == "Confirmed real"
        checks = _sheet(d, "Checks")
        assert checks[checks["Check ID"] == "CHK-DQ-1"].iloc[0]["Excluded"] != "Yes"
        assert _rows(page, "listrow_net_dq_").count() == 1

        # voided with a reason: the check is excluded, and the audit log says so
        page.locator('[class*="st-key-listrow_net_dq_CHK-DQ-2"] button').click()
        expect(page.get_by_role("heading", name="R1-WAI-001", exact=True)).to_be_visible(timeout=30_000)
        page.get_by_placeholder("For example: bench test while setting up").fill("Bench test while setting up")
        page.locator('[role="heading"][aria-level="1"]').first.click()
        page.wait_for_timeout(600)
        page.get_by_role("button", name="Void as test data", exact=True).click()
        expect(page.get_by_text("Voided as test data.", exact=True)).to_be_visible(timeout=30_000)
        checks = _sheet(d, "Checks")
        row = checks[checks["Check ID"] == "CHK-DQ-2"].iloc[0]
        assert row["Excluded"] == "Yes" and row["Exclusion Reason"] == "Bench test while setting up"
        audit = _sheet(d, "Audit Log")
        assert ((audit["Record ID"] == "CHK-DQ-2") & (audit["Field"] == "Excluded") & (audit["New Value"] == "Yes")).any()
        # nothing left: the all-clear panel
        expect(page.get_by_text("Nothing is waiting", exact=True)).to_be_visible(timeout=30_000)
        expect(page.get_by_text("Every check has other activity nearby.", exact=True)).to_be_visible()


# ---------------------------------------------------------------- Window start corrections (AdmWinFix)

from test_button_loading_feedback_tier2 import suspect_r1_window_app  # noqa: E402,F401  (the fixture: one R1 trap whose earliest window starts after it was deployed)


def test_a_window_start_is_corrected_one_trap_at_a_time_and_needs_a_reason(page: Page, suspect_r1_window_app) -> None:
    url, data_dir, seeded = suspect_r1_window_app
    page.set_viewport_size(DESKTOP)
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    ap.open_data_page(page, "Window start corrections")
    card = page.locator(f'[class*="st-key-card_winfix_{seeded["trap_id"]}"]')
    expect(card).to_be_visible(timeout=15_000)
    expect(page.get_by_text("1 R1 trap flagged", exact=False)).to_be_visible()
    # the board's fields: both starts as facts, the true deployment as a date and a time that begin at the deployment start
    assert "Current earliest start" in card.inner_text() and "Deployment Start" in card.inner_text()
    assert card.locator('[data-testid="stDateInput"] input').first.input_value() == "01/08/2026"

    # refused: no reason, so the field is ringed and a line says why; nothing is written
    card.get_by_role("button", name="Apply this trap", exact=True).click()
    expect(page.get_by_text("Say how the true deployment date was confirmed.", exact=True)).to_be_visible(timeout=15_000)
    assert page.locator('[class*="st-key-fielderr_reason_winfix"]').count() == 1
    windows = _sheet(data_dir, "Windows")
    assert windows[windows["Window ID"] == seeded["window_id"]].iloc[0]["Start Time"].startswith("2026-08-05 09:00")

    page.get_by_role("textbox", name="Reason", exact=True).fill("Starts were stamped at sign-up, not deployment.")
    page.locator('[role="heading"][aria-level="1"]').first.click()
    page.wait_for_timeout(1_500)
    card.get_by_role("button", name="Apply this trap", exact=True).click()
    expect(page.get_by_text(f'{seeded["trap_id"]} corrected.', exact=True)).to_be_visible(timeout=30_000)
    windows = _sheet(data_dir, "Windows")
    assert windows[windows["Window ID"] == seeded["window_id"]].iloc[0]["Start Time"].startswith("2026-08-01 00:00")
    audit = _sheet(data_dir, "Audit Log")
    assert ((audit["Record ID"] == seeded["window_id"]) & (audit["Reason"] == "Starts were stamped at sign-up, not deployment.")).any()


def test_the_menus_data_and_records_goes_to_the_list_from_any_of_its_pages(page: Page, tmp_path: Path) -> None:
    """The menu item is "here" only on the list itself; inside a correction, Trial periods, the audit log or export it is a way back to the list, on a desktop and on a phone."""
    with _serve(tmp_path / "d", ADMIN_SEED) as url:
        for viewport in (DESKTOP, PHONE):
            page.set_viewport_size(viewport)
            _open(page, url, "Data & records")
            for title in ("Field check", "Trial periods", "Audit log", "Export and backup"):
                page.get_by_role("button", name=title, exact=True).click()
                expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible(timeout=30_000)
                ap.go_to(page, "Data & records")
                expect(page.get_by_role("heading", name="Data & records", exact=True)).to_be_visible(timeout=30_000)
                assert page.get_by_role("button", name=title, exact=True).count() == 1, "the list, with every page on it again"


def test_a_build_is_labelled_with_its_product_once_everywhere_it_is_named(page: Page, tmp_path: Path) -> None:
    """Reviewer, 20 Oct: the trap page said "R1 · R1 Build 4.3". The label is the product, a dot, then the build ("R1 · Build 4.3"), wherever a build is named."""
    page.set_viewport_size(DESKTOP)
    with _serve(tmp_path / "d", ADMIN_SEED) as url:
        def no_doubled(where: str) -> None:
            text = page.locator(".st-key-r1_screen").first.inner_text()
            assert "R1 · R1 " not in text and "M1 · M1 " not in text, f"{where}: a doubled product in {text!r}"

        ap.open_trap(page, url, "R1-MAN-001")
        expect(page.locator(".r1-kv").filter(has_text="Build").first).to_contain_text("R1 · Build 4.3")
        no_doubled("trap page")
        ap.open_trap(page, url, "R1-MAN-NEW1")
        ap.action(page, "Change build", "Change build of R1-MAN-NEW1")
        expect(page.get_by_text("R1 · Build 4.3", exact=True).first).to_be_visible()
        no_doubled("Change build")
        ap.go_to(page, "Traps")
        page.locator('[class*="st-key-listrow_net_R1-MAN-001"] button').click()
        expect(page.locator(".r1-stats3")).to_be_visible(timeout=30_000)
        no_doubled("trap history")
        ap.go_to(page, "Trial setup")
        page.get_by_role("radio", name="Builds", exact=True).click()
        page.wait_for_timeout(1_500)
        no_doubled("Builds")
        ap.open_data_page(page, "Trial periods")
        page.get_by_role("radio", name="All", exact=True).click()
        page.wait_for_timeout(1_200)
        no_doubled("Trial periods")
