"""Part B batch 2a, Trial setup (boards AdmSetupTraps, AdmSetupTrapsPhone, AdmAddTrap, AdmBulkSelect, AdmBulkPreview, AdmSites, AdmBuilds, AdmSiteRename,
AdmSiteRemove): a segmented control (Traps / Trap sites / Builds), site chips, rows with a status dot and an Edit button, Add trap as a side panel (its own screen on
a phone), Bulk activate as its own page, Rename site code and Permanently remove as their own pages. What each writes is today's. Local test data only."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
import admin_page as ap  # noqa: E402
import task_form as tf  # noqa: E402
from admin_seed import ADMIN_SEED  # noqa: E402
from test_check_save_golden_ui import _serve  # noqa: E402
from test_trial_model_ui import _sheet  # noqa: E402

# An Inactive site with nothing at it (so it can be removed), and an Inactive R1 trap at Kaitoke Shed, which runs no trial (so bulk activation must skip it).
SEED = ADMIN_SEED + """
    import app, pandas as pd
    d = app.load_data()
    row = {c: "" for c in app.SHEETS["Sites"]}
    row.update({"Site ID": "TRK", "Site Name": "Te Raekaihau", "Visit Interval Days": "3", "Mobile Coverage Confirmed": "No", "Status": "Inactive"})
    d["Sites"] = pd.concat([d["Sites"], pd.DataFrame([row])], ignore_index=True)
    trap = {c: "" for c in app.SHEETS["Traps"]}
    trap.update({"Trap ID": "R1-KAI-NEW1", "Product": "R1", "Build Version": "R1 Build 4.3", "Site ID": "KAI", "Route Order": "60", "Location": "Spot kai", "Status": "Inactive"})
    d["Traps"] = pd.concat([d["Traps"], pd.DataFrame([trap])], ignore_index=True)
    app.save_data(d)
"""


def _section(page: Page, name: str) -> None:
    page.get_by_role("radio", name=name, exact=True).click()
    page.wait_for_timeout(1200)


def _row(page: Page, key: str):
    return page.locator(f'[class*="st-key-{key}"]').first


expect.set_options(timeout=45_000)  # these pages are drawn by a server that is sometimes slow to wake; a long wait costs nothing when it is not needed

# --- Traps ------------------------------------------------------------------------------------------------------------------

def test_the_traps_section_lists_every_trap_with_its_status_and_filters_by_site(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 1280, "height": 1000})
    with _serve(data_dir, SEED) as url:
        ap.open_trial_setup(page, url)
        assert page.locator('[role="heading"][aria-level="1"]').all_inner_texts() == ["Trial setup"]
        expect(page.get_by_role("radio", name="Traps", exact=True)).to_be_checked()
        row = _row(page, "listrow_trap_R1-MAN-001").inner_text()
        assert "R1-MAN-001" in row and "Active" in row and "Mangaroa Farm" in row and "CAM-001" in row and "4.3" in row, row
        assert "Inactive" in _row(page, "listrow_trap_R1-MAN-NEW1").inner_text()
        expect(page.get_by_role("button", name=re.compile(r"^Bulk activate \(\d+\)$"))).to_be_visible()
        page.get_by_role("radio", name="Kaitoke Shed", exact=True).click()
        page.wait_for_timeout(1200)
        assert page.locator('[class*="st-key-listrow_trap_R1-MAN-001"]').count() == 0 and page.locator('[class*="st-key-listrow_trap_R1-KAI-001"]').count() == 1
        page.locator('[class*="st-key-setup_edit_trap_R1-KAI-001"] button').click()
        expect(page.get_by_role("heading", name="R1-KAI-001", exact=True)).to_be_visible(timeout=30_000)


def test_add_trap_opens_beside_the_list_on_desktop_refuses_a_missing_or_used_id_and_writes_the_row(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 1280, "height": 1000})
    with _serve(data_dir, SEED) as url:
        ap.open_trial_setup(page, url)
        page.get_by_role("button", name="Add trap", exact=True).first.click()
        expect(page.get_by_text("The permanent physical ID, without a site code.", exact=True)).to_be_visible(timeout=15_000)
        panel, rows = page.locator('[class*="st-key-card_setup_panel"]').bounding_box(), _row(page, "listrow_trap_R1-MAN-001").bounding_box()
        assert panel["x"] > rows["x"] + rows["width"] - 5, "the panel is beside the list"
        page.get_by_role("button", name="Add trap", exact=True).last.click()
        expect(page.get_by_text("Enter the trap's ID.", exact=True)).to_have_count(2, timeout=15_000)
        page.wait_for_timeout(2_000)  # a refused tap's reruns settle before the next edit (typing into them races the button's second pass)
        ap.fill(page, "Trap ID", "R1-MAN-001")
        page.get_by_role("button", name="Add trap", exact=True).last.click()
        expect(page.get_by_text("That Trap ID already exists.", exact=True)).to_have_count(2, timeout=15_000)
        page.wait_for_timeout(2_000)
        ap.fill(page, "Trap ID", "R16-13")
        ap.fill(page, "Location description", "By the gate")
        page.get_by_role("button", name="Add trap", exact=True).last.click()
        expect(page.get_by_text("R16-13 added.", exact=True)).to_be_visible(timeout=60_000)
    row = _sheet(data_dir, "Traps").query("`Trap ID` == 'R16-13'").iloc[0]
    assert (row["Status"], row["Site ID"], row["Location"], row["Deployment Start"], row["Product"]) == ("Inactive", "MAN", "By the gate", "", "R1")


def test_on_a_phone_add_trap_is_its_own_screen_with_a_way_back(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, SEED) as url:
        ap.open_trial_setup(page, url)
        page.get_by_role("button", name="Add trap", exact=True).first.click()
        expect(page.get_by_text("The permanent physical ID, without a site code.", exact=True)).to_be_visible(timeout=15_000)
        assert not _row(page, "listrow_trap_R1-MAN-001").is_visible(), "the list is not drawn under the panel on a phone"
        page.get_by_role("button", name="Back to Trial setup", exact=True).click()
        expect(_row(page, "listrow_trap_R1-MAN-001")).to_be_visible(timeout=15_000)


# --- Bulk activate ----------------------------------------------------------------------------------------------------------

def test_bulk_activate_is_its_own_page_locks_its_preview_and_names_a_trap_it_had_to_skip(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 1000})
    with _serve(data_dir, SEED) as url:
        ap.open_trial_setup(page, url)
        page.get_by_role("button", name=re.compile(r"^Bulk activate \(\d+\)$")).click()
        expect(page.get_by_role("heading", name="Bulk activate traps", exact=True)).to_be_visible(timeout=15_000)
        preview = page.get_by_role("button", name="Preview activation", exact=True)
        preview.click()
        expect(page.get_by_text("2 things to finish", exact=True)).to_be_visible(timeout=15_000)
        ap.tick(page, "R1-MAN-NEW1")
        ap.tick(page, "R1-KAI-NEW1")
        ap.fill(page, "Reason", "Second line added to the trial.")
        preview.click()
        expect(page.get_by_text("Confirm 2 traps", exact=True)).to_be_visible(timeout=15_000)
        expect(page.get_by_text("The choices are locked while this preview is open. Cancel to change them.", exact=True)).to_be_visible()
        assert page.get_by_role("checkbox", name="R1-MAN-NEW1", exact=True).is_disabled(), "what is previewed is exactly what is committed"
        page.get_by_role("button", name="Activate 2 traps", exact=True).click()
        expect(page.get_by_text("Bulk activation applied.", exact=True)).to_be_visible(timeout=60_000)
        expect(page.get_by_text("Skipped: R1-KAI-NEW1", exact=False)).to_be_visible()
    traps = _sheet(data_dir, "Traps").set_index("Trap ID")
    assert traps.loc["R1-MAN-NEW1", "Status"] == "Active" and traps.loc["R1-KAI-NEW1", "Status"] == "Inactive"
    windows = _sheet(data_dir, "Windows")
    opened = windows[(windows["Trap ID"] == "R1-MAN-NEW1") & (windows["Status"] == "Open")]
    assert len(opened) == 1 and opened.iloc[0]["Trial ID"] != ""
    assert windows[windows["Trap ID"] == "R1-KAI-NEW1"].empty


# --- Trap sites -------------------------------------------------------------------------------------------------------------

def test_a_site_cannot_be_made_active_without_coverage_or_inactive_with_active_traps_and_saves_what_it_shows(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 1280, "height": 1100})
    with _serve(data_dir, SEED) as url:
        ap.open_trial_setup(page, url)
        _section(page, "Trap sites")
        assert "Active" in _row(page, "listrow_site_MAN").inner_text() and "Every 3 days" in _row(page, "listrow_site_MAN").inner_text()
        page.locator('[class*="st-key-setup_edit_site_MAN"] button').click()
        expect(page.get_by_text("Fixed at 3 days for this trial design.", exact=True)).to_be_visible(timeout=15_000)
        tf.choose(page, "Status", "Inactive")
        page.get_by_role("button", name="Save site changes", exact=True).click()
        expect(page.get_by_text("Move or deactivate the 4 active traps at this site before making it inactive.", exact=False)).to_have_count(2, timeout=15_000)
        tf.choose(page, "Status", "Active")
        tf.choose(page, "Mobile coverage confirmed?", "No")
        page.get_by_role("button", name="Save site changes", exact=True).click()
        expect(page.get_by_text("Confirm reliable mobile coverage before activating this site.", exact=True)).to_have_count(2, timeout=15_000)
        tf.choose(page, "Mobile coverage confirmed?", "Yes")
        ap.fill(page, "Notes", "Gate code 1234.")
        page.get_by_role("button", name="Save site changes", exact=True).click()
        expect(page.get_by_text("Mangaroa Farm saved.", exact=True)).to_be_visible(timeout=60_000)
    site = _sheet(data_dir, "Sites").query("`Site ID` == 'MAN'").iloc[0]
    assert (site["Status"], site["Mobile Coverage Confirmed"], site["Notes"], site["Visit Interval Days"]) == ("Active", "Yes", "Gate code 1234.", "3")


def test_rename_site_code_is_its_own_page_that_counts_what_it_updates_and_changes_every_linked_record(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 1280, "height": 1100})
    with _serve(data_dir, SEED) as url:
        before = _sheet(data_dir, "Traps")["Site ID"].value_counts().to_dict()
        ap.open_trial_setup(page, url)
        _section(page, "Trap sites")
        page.locator('[class*="st-key-setup_edit_site_WAI"] button').click()
        expect(page.get_by_text("Rename site code", exact=True)).to_be_visible(timeout=15_000)
        page.get_by_role("button", name="Rename", exact=True).click()
        expect(page.get_by_role("heading", name="Rename site code", exact=True)).to_be_visible(timeout=15_000)
        card = page.locator('[class*="st-key-card_site_counts"]').inner_text()
        assert "This will update" in card and "Traps" in card and str(before.get("WAI", 0)) in card, card
        expect(page.get_by_text("This changes every record linked to WAI", exact=True)).to_be_visible()
        rename = page.get_by_role("button", name="Rename site code", exact=True)
        expect(rename).to_be_disabled()
        ap.fill(page, "New site code", "WRP")
        ap.fill(page, "Reason", "The site was renamed on the map.")
        ap.tick(page, "I understand this updates every linked Site ID and moves linked evidence files")
        page.get_by_role("button", name="Rename to WRP", exact=True).click()
        expect(page.get_by_text("Site code changed from WAI to WRP.", exact=True)).to_be_visible(timeout=60_000)
    traps = _sheet(data_dir, "Traps")
    assert (traps["Site ID"] == "WAI").sum() == 0 and (traps["Site ID"] == "WRP").sum() == before["WAI"]
    assert "WRP" in _sheet(data_dir, "Sites")["Site ID"].tolist()


def test_remove_site_is_its_own_page_for_an_inactive_site_and_unlocks_only_on_the_typed_name_and_the_tick(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 1280, "height": 1100})
    with _serve(data_dir, SEED) as url:
        ap.open_trial_setup(page, url)
        _section(page, "Trap sites")
        page.locator('[class*="st-key-setup_edit_site_MAN"] button').click()
        expect(page.get_by_text("Rename site code", exact=True)).to_be_visible(timeout=15_000)
        assert page.get_by_text("Permanently remove this site", exact=True).count() == 0, "an Active site cannot be removed, so no Remove is offered"
        page.locator('[class*="st-key-setup_edit_site_TRK"] button').click()
        expect(page.get_by_text("Permanently remove this site", exact=True)).to_be_visible(timeout=15_000)
        page.get_by_role("button", name="Remove", exact=True).click()
        expect(page.get_by_role("heading", name="Remove Te Raekaihau", exact=True)).to_be_visible(timeout=15_000)
        remove = page.get_by_role("button", name="Remove permanently", exact=True)
        expect(remove).to_be_disabled()
        ap.fill(page, "Reason", "Never used.")
        ap.fill(page, "Site name", "Te Raek")
        ap.tick(page, "I understand this permanently deletes real trial history and can't be undone")
        expect(remove).to_be_disabled()
        ap.fill(page, "Site name", "Te Raekaihau")
        expect(remove).to_be_enabled(timeout=15_000)
        remove.click()
        expect(page.get_by_text("Te Raekaihau permanently removed.", exact=True)).to_be_visible(timeout=60_000)
    assert "TRK" not in _sheet(data_dir, "Sites")["Site ID"].tolist()


# --- Builds -----------------------------------------------------------------------------------------------------------------

def test_builds_are_listed_with_their_status_and_a_new_one_is_refused_when_it_already_exists(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 1280, "height": 1100})
    with _serve(data_dir, SEED) as url:
        ap.open_trial_setup(page, url)
        _section(page, "Builds")
        text = page.locator('[class*="st-key-tablewrap_setup_builds"]').inner_text()
        assert "R1 · Build 4.3" in text and "Active traps" in text and "First active" in text and "Source" in text, text
        page.get_by_role("button", name="Add build", exact=True).click()
        expect(page.get_by_role("radiogroup", name="Build status")).to_be_visible(timeout=15_000)
        ap.fill(page, "Build version", "R1 Build 4.3")
        page.get_by_role("button", name="Add build", exact=True).last.click()
        expect(page.get_by_text("That build version already exists for this trap type.", exact=True)).to_have_count(2, timeout=15_000)
        ap.fill(page, "Build version", "R1 Build 4.4")
        tf.choose(page, "Build status", "Trial comparison")
        page.get_by_role("button", name="Add build", exact=True).last.click()
        expect(page.get_by_text("R1 Build 4.4 saved.", exact=True)).to_be_visible(timeout=60_000)
    row = _sheet(data_dir, "Builds").query("`Build Version` == 'R1 Build 4.4'").iloc[0]
    assert (row["Product"], row["Build Status"]) == ("R1", "Trial comparison")
