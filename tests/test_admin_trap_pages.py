"""Part B batch 2a, the trap page and its five action pages (boards AdmTrapActive, AdmTrapInactive, AdmTrapPhone, AdmActivate, AdmActivateRefused, AdmDeactivate,
AdmMove, AdmChangeBuild, AdmDelete).

The trap page splits the details form from the actions, lists every action that exists for the trap's state and says why one is not available; every action that
opens or closes a window is its own page (what will happen, a reason, the effective time, a confirm tick, a button named for it) and writes what it always wrote.
Local test data only (tests/admin_seed.py)."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
import admin_page as ap  # noqa: E402
import task_form as tf  # noqa: E402
from admin_seed import ADMIN_SEED  # noqa: E402
from test_check_save_golden_ui import _serve  # noqa: E402
from test_trial_model_ui import _sheet  # noqa: E402

ACTIVE, INACTIVE_HISTORY, INACTIVE_UNUSED = "R1-MAN-001", "R1-MAN-005", "R1-MAN-NEW1"


def _trap(data_dir: Path, trap_id: str) -> pd.Series:
    frame = _sheet(data_dir, "Traps")
    return frame[frame["Trap ID"] == trap_id].iloc[0]


def _audit(data_dir: Path, trap_id: str) -> pd.DataFrame:
    frame = _sheet(data_dir, "Audit Log")
    return frame[frame["Record ID"] == trap_id]


def _text(page: Page, selector: str) -> str:
    return page.locator(selector).first.inner_text()


expect.set_options(timeout=45_000)  # these pages are drawn by a server that is sometimes slow to wake; a long wait costs nothing when it is not needed

# --- The trap page ----------------------------------------------------------------------------------------------------------

def test_an_active_trap_lists_its_actions_and_says_why_the_ones_it_cannot_do_are_unavailable(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 1280, "height": 1000})
    with _serve(data_dir, ADMIN_SEED) as url:
        ap.open_trap(page, url, ACTIVE)
        assert page.locator('[role="heading"][aria-level="1"]').all_inner_texts() == [ACTIVE]
        facts = _text(page, '[class*="st-key-card_trap_facts"]')
        for kept in ("Build", "Trial", "Running since", "Open test window", "since"):
            assert kept in facts, (kept, facts)
        actions = _text(page, '[class*="st-key-card_trap_actions"]')
        assert "Deactivate" in actions and "Closes the open test window and takes the trap out of service." in actions
        assert "Builds can't change inside a trial. End the trial at Mangaroa Farm first." in actions, "Change build stays listed, with the reason"
        assert "Deactivate the trap first. An Active trap can't move." in actions, "so does Move"
        for absent in ("Activate\n", "Delete this trap"):
            assert absent not in actions, absent
        expect(page.get_by_role("button", name="Go to trial", exact=True)).to_be_visible()
        assert page.get_by_role("button", name="Change build", exact=True).count() == 0 and page.get_by_role("button", name="Move", exact=True).count() == 0
        # Desktop: the details are the left column, the facts and actions the right one.
        details, side = page.locator('[class*="st-key-card_trap_details"]').bounding_box(), page.locator('[class*="st-key-card_trap_facts"]').bounding_box()
        assert details["x"] < side["x"], "details on the left"


def test_an_inactive_unused_trap_lists_activate_change_build_move_and_delete(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 1280, "height": 1000})
    with _serve(data_dir, ADMIN_SEED) as url:
        ap.open_trap(page, url, INACTIVE_UNUSED)
        actions = _text(page, '[class*="st-key-card_trap_actions"]')
        for kept in ("Activate", "Starts a new test window, stamped with the site's running trial.", "Change build", "Stages a build before a trial. No window is opened.",
                     "Move to another site", "Delete this trap", "It has no checks, tasks or photos, so it can be removed."):
            assert kept in actions, (kept, actions)
        for name in ("Activate", "Change build", "Move", "Delete"):
            expect(page.get_by_role("button", name=name, exact=True)).to_be_visible()
        ap.open_trap(page, url, INACTIVE_HISTORY)
        assert page.get_by_role("button", name="Delete", exact=True).count() == 0, "a trap with a window of history cannot be deleted, so no Delete is offered"


def test_a_phone_shows_the_facts_and_actions_before_the_details(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, ADMIN_SEED) as url:
        ap.open_trap(page, url, ACTIVE)
        facts, actions, details = (page.locator(f'[class*="st-key-card_trap_{n}"]').bounding_box() for n in ("facts", "actions", "details"))
        assert facts["y"] < actions["y"] < details["y"], (facts, actions, details)
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scroll"


def test_saving_the_details_writes_the_four_fields_and_nothing_else(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 1280, "height": 1000})
    with _serve(data_dir, ADMIN_SEED) as url:
        before = {n: _sheet(data_dir, n) for n in ("Windows", "Sites", "Builds", "Trials")}
        ap.open_trap(page, url, ACTIVE)
        ap.fill(page, "Location description", "Gully track, second bend")
        ap.fill(page, "Camera ID", "CAM-07")
        ap.fill(page, "Notes", "Moved 3 m uphill after the flood.")
        page.get_by_role("button", name="Save changes", exact=True).click()
        expect(page.get_by_text(f"{ACTIVE} updated.", exact=True)).to_be_visible(timeout=30_000)
    row = _trap(data_dir, ACTIVE)
    assert (row["Location"], row["Camera ID"], row["Notes"]) == ("Gully track, second bend", "CAM-07", "Moved 3 m uphill after the flood.")
    for name, frame in before.items():
        pd.testing.assert_frame_equal(_sheet(data_dir, name), frame, obj=name)


# --- Deactivate -------------------------------------------------------------------------------------------------------------

def test_deactivate_asks_a_reason_and_a_time_not_before_the_open_window_and_closes_it_with_an_audit_row(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, ADMIN_SEED) as url:
        ap.open_trap(page, url, ACTIVE)
        ap.action(page, "Deactivate", f"Deactivate {ACTIVE}")
        card = _text(page, '[class*="st-key-card_happen"]')
        assert "Closes the test window open since" in card and f"Sets {ACTIVE} to Inactive." in card and "Starts no new window." in card
        deactivate = page.get_by_role("button", name=f"Deactivate {ACTIVE}", exact=True)
        expect(deactivate).to_be_disabled()  # the tick is what enables it
        ap.tick(page, "Close the current window and set this trap to Inactive")
        deactivate.click()
        expect(page.get_by_text("1 thing to finish", exact=True)).to_be_visible(timeout=15_000)
        expect(page.get_by_text("Say why the trap is being deactivated.", exact=True)).to_have_count(2)
        assert _trap(data_dir, ACTIVE)["Status"] == "Active", "a refused save writes nothing"
        ap.fill(page, "Reason", "Trap damaged by stock.")
        # The open window started when the trial did (1 Sep in the seed): a time before it is refused, in words that name it.
        tf.set_when(page, f"deactivate_when_{ACTIVE}", datetime.now() - timedelta(days=90))
        deactivate.click()
        expect(page.locator(".r1-fielderr").filter(has_text="Effective from can't be before the open window started")).to_have_count(1, timeout=15_000)
        expect(page.get_by_role("button", name="Deactivating…")).to_have_count(0, timeout=15_000)  # the refusal has settled: Save is back to its name (typing before then races the click's own runs)
        page.wait_for_timeout(1000)
        assert _trap(data_dir, ACTIVE)["Status"] == "Active"
        when = (datetime.now() - timedelta(hours=2)).replace(second=0, microsecond=0)
        tf.set_when(page, f"deactivate_when_{ACTIVE}", when)
        deactivate.click()
        expect(page.get_by_text(f"{ACTIVE} deactivated.", exact=True)).to_be_visible(timeout=60_000)
    assert _trap(data_dir, ACTIVE)["Status"] == "Inactive"
    windows = _sheet(data_dir, "Windows")
    closed = windows[(windows["Trap ID"] == ACTIVE) & (windows["End Reason"] == "Trap deactivated")]
    assert len(closed) == 1 and closed.iloc[0]["End Time"] == when.strftime("%Y-%m-%d %H:%M:%S") and closed.iloc[0]["Review Status"] == "Not required"
    assert windows[(windows["Trap ID"] == ACTIVE) & (windows["Status"] == "Open")].empty, "no new window starts"
    audit = _audit(data_dir, ACTIVE)
    mine = audit[audit["Reason"] == "Trap damaged by stock."]
    assert len(mine) == 1 and mine.iloc[0]["Field"] == "Status" and (mine.iloc[0]["Previous Value"], mine.iloc[0]["New Value"]) == ("Active", "Inactive")


# --- Activate ---------------------------------------------------------------------------------------------------------------

def test_activate_with_no_trial_running_is_an_error_panel_with_a_way_to_start_one(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    seed = ADMIN_SEED + """
    import app
    d = app.load_data()
    d["Trials"].loc[d["Trials"]["Site ID"] == "MAN", ["Status", "End Time"]] = ["Ended", app.dtstr(app.now())]
    app.save_data(d)
"""
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, seed) as url:
        ap.open_trap(page, url, INACTIVE_UNUSED)
        ap.action(page, "Activate", f"Activate {INACTIVE_UNUSED}")
        expect(page.get_by_text("No trial is running at Mangaroa Farm", exact=True)).to_be_visible()
        expect(page.get_by_text("A trap can only start a test window inside a trial. Start one first.", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Start a trial", exact=True)).to_be_visible()
        assert page.get_by_role("button", name=f"Activate {INACTIVE_UNUSED}", exact=True).count() == 0, "no form when it would only be refused"
        before = _sheet(data_dir, "Traps")
    pd.testing.assert_frame_equal(_sheet(data_dir, "Traps"), before)


def test_activate_inside_a_running_trial_starts_a_window_stamped_with_the_trial(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, ADMIN_SEED) as url:
        ap.open_trap(page, url, INACTIVE_UNUSED)
        ap.action(page, "Activate", f"Activate {INACTIVE_UNUSED}")
        card = _text(page, '[class*="st-key-card_happen"]')
        assert "Starts a new test window from the time below, stamped with trial" in card and f"Sets {INACTIVE_UNUSED} to Active." in card
        ap.fill(page, "Reason", "Added to the trial line.")
        ap.tick(page, "Start a new monitoring window and set this trap to Active")
        page.get_by_role("button", name=f"Activate {INACTIVE_UNUSED}", exact=True).click()
        expect(page.get_by_text(f"{INACTIVE_UNUSED} activated.", exact=True)).to_be_visible(timeout=60_000)
    assert _trap(data_dir, INACTIVE_UNUSED)["Status"] == "Active"
    windows = _sheet(data_dir, "Windows")
    opened = windows[(windows["Trap ID"] == INACTIVE_UNUSED) & (windows["Status"] == "Open")]
    assert len(opened) == 1 and opened.iloc[0]["Trial ID"] != ""
    assert "Added to the trial line." in _audit(data_dir, INACTIVE_UNUSED)["Reason"].tolist()


# --- Move -------------------------------------------------------------------------------------------------------------------

def test_move_is_refused_while_a_visit_is_in_progress_and_changes_nothing_then_moves_the_trap(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    seed = ADMIN_SEED + """
    import app
    d = app.load_data()
    d["Visits"].loc[d["Visits"].index[0], "Status"] = "In progress"
    app.save_data(d)
"""
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, seed) as url:
        ap.open_trap(page, url, INACTIVE_UNUSED)
        ap.action(page, "Move", f"Move {INACTIVE_UNUSED}")
        expect(page.get_by_text("Can't move while a visit is in progress at either site.", exact=True)).to_be_visible()
        card = _text(page, '[class*="st-key-card_happen"]')
        assert f"Moves {INACTIVE_UNUSED} from Mangaroa Farm to the site below." in card and "Opens no window (the trap stays Inactive)." in card
        move = page.get_by_role("button", name=f"Move {INACTIVE_UNUSED}", exact=True)
        tf.choose(page, "Destination site", "Kaitoke Shed")
        ap.fill(page, "Location at destination", "North fence, post 4")
        ap.fill(page, "Reason", "Moving to the new line.")
        ap.tick(page, "Move this trap to the destination site")
        before = _sheet(data_dir, "Traps")
        move.click()
        expect(page.get_by_text("Finish or pause active visits at the source and destination sites before moving this trap.", exact=False)).to_be_visible(timeout=30_000)
        pd.testing.assert_frame_equal(_sheet(data_dir, "Traps"), before)
    # The same move with the visit finished.
    data_dir2 = tmp_path / "e"; data_dir2.mkdir()
    with _serve(data_dir2, ADMIN_SEED) as url:
        ap.open_trap(page, url, INACTIVE_UNUSED)
        ap.action(page, "Move", f"Move {INACTIVE_UNUSED}")
        tf.choose(page, "Destination site", "Kaitoke Shed")
        ap.fill(page, "Location at destination", "North fence, post 4")
        ap.fill(page, "Reason", "Moving to the new line.")
        ap.tick(page, "Move this trap to the destination site")
        page.get_by_role("button", name=f"Move {INACTIVE_UNUSED}", exact=True).click()
        expect(page.get_by_text(f"{INACTIVE_UNUSED} moved.", exact=True)).to_be_visible(timeout=60_000)
        expect(page.get_by_text("New site: Kaitoke Shed.", exact=True)).to_be_visible()
    row = _trap(data_dir2, INACTIVE_UNUSED)
    assert (row["Site ID"], row["Location"], row["Status"]) == ("KAI", "North fence, post 4", "Inactive")
    audit = _audit(data_dir2, INACTIVE_UNUSED)
    assert {"Site ID", "Route Order", "Location"} <= set(audit["Field"]) and set(audit["Reason"]) == {"Moving to the new line."}
    windows = _sheet(data_dir2, "Windows")
    assert windows[windows["Trap ID"] == INACTIVE_UNUSED].empty, "an Inactive trap opens no window"


# --- Change build -----------------------------------------------------------------------------------------------------------

def test_change_build_stages_a_build_on_an_inactive_trap_and_opens_no_window(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, ADMIN_SEED) as url:
        builds = [b for b in _sheet(data_dir, "Builds")["Build Version"].tolist() if b != "R1 Build 4.3"]
        ap.open_trap(page, url, INACTIVE_UNUSED)
        ap.action(page, "Change build", f"Change build of {INACTIVE_UNUSED}")
        expect(page.get_by_text("Current build", exact=True)).to_be_visible()
        expect(page.get_by_text("The trap is Inactive, so this stages the build before a trial. No window is opened.", exact=True)).to_be_visible()
        change = page.get_by_role("button", name="Change build", exact=True)
        ap.tick(page, "Change this trap's build")
        change.click()
        expect(page.get_by_text("2 things to finish", exact=True)).to_be_visible(timeout=15_000)
        assert _trap(data_dir, INACTIVE_UNUSED)["Build Version"] == "R1 Build 4.3", "a refused save writes nothing"
        options = page.locator('[class*="st-key-rows_build_new"] [data-testid="stRadioOption"]')
        assert options.count() >= 1, "there is another build to choose"
        options.first.click()
        chosen = options.first.inner_text().split("\n")[0].split(" · ")[-1].strip()
        ap.fill(page, "Reason", "Upgraded on the bench.")
        change.click()
        expect(page.get_by_text(f"{INACTIVE_UNUSED} build changed.", exact=True)).to_be_visible(timeout=60_000)
    assert _trap(data_dir, INACTIVE_UNUSED)["Build Version"] == chosen != "R1 Build 4.3"
    assert _sheet(data_dir, "Windows").query("`Trap ID` == @INACTIVE_UNUSED").empty
    assert "Upgraded on the bench." in _audit(data_dir, INACTIVE_UNUSED)["Reason"].tolist()


# --- Delete -----------------------------------------------------------------------------------------------------------------

def test_delete_an_unused_trap_asks_a_reason_and_writes_the_audit_row_in_the_same_save(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, ADMIN_SEED) as url:
        ap.open_trap(page, url, INACTIVE_UNUSED)
        ap.action(page, "Delete", f"Delete {INACTIVE_UNUSED}")
        expect(page.get_by_text("This can't be undone", exact=True)).to_be_visible()
        delete = page.get_by_role("button", name=f"Delete {INACTIVE_UNUSED}", exact=True)
        ap.tick(page, f"Delete {INACTIVE_UNUSED}")
        delete.click()
        expect(page.get_by_text("Say why the trap is being deleted.", exact=True)).to_have_count(2, timeout=15_000)
        assert (_sheet(data_dir, "Traps")["Trap ID"] == INACTIVE_UNUSED).any(), "a refused save deletes nothing"
        ap.fill(page, "Reason", "Added by mistake (duplicate of R1-MAN-004).")
        delete.click()
        expect(page.get_by_text(f"{INACTIVE_UNUSED} deleted.", exact=True)).to_be_visible(timeout=60_000)
    assert not (_sheet(data_dir, "Traps")["Trap ID"] == INACTIVE_UNUSED).any()
    audit = _audit(data_dir, INACTIVE_UNUSED)
    assert len(audit) == 1 and audit.iloc[0]["Field"] == "Deleted" and audit.iloc[0]["Reason"] == "Added by mistake (duplicate of R1-MAN-004)."
