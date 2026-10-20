"""Phase 6: the check form in the 7a language (boards `P6*`, canvas v21), through the real page.

What the boards decide and these tests hold: one back pill; the Routine card and the six outcomes; the "What you found" card and Change
(answers that still apply are kept); the Routine confirm screen and "Record something different" (nothing pre-ticked); an error summary above
Save and a line at each field, and Save never stuck on "Saving check…" after a refusal; Save waits for photos; the two no-window screens;
the trap list's saved panel; the desktop column. What Save writes is held by the golden record (test_check_save_golden*.py), not here."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import check_form as cf  # noqa: E402
import check_save_matrix as m  # noqa: E402
import photo_integrity as pi  # noqa: E402
from test_check_save_golden_ui import SEED_NO_WINDOW, WORKBOOK, _frozen_rows, _normalise, _serve  # noqa: E402

CAM = m.PROFILES["camera_trial"]["trap"]
NOCAM = m.PROFILES["nocamera_trial"]["trap"]
SIX = ["Trap still set, no animal", "Dead animal found", "Trap fired, no animal", "Trap disturbed", "Trap missing", "Unable to check"]


def _sheet(data_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_excel(data_dir / WORKBOOK, sheet_name=name, dtype=str).fillna("")


@pytest.fixture
def phone(page: Page) -> Page:
    page.set_viewport_size({"width": 414, "height": 896})
    return page


def _save_button(page: Page):
    return page.get_by_role("button", name=re.compile(r"^(Save check|Please wait|Saving check…)$"))


# ---------------------------------------------------------------- the start screen
def test_the_start_screen_offers_routine_and_the_six_outcomes_with_one_back_pill(tmp_path, phone: Page):
    with _serve(tmp_path / "d") as url:
        cf.start_visit_and_open(phone, url, CAM)
        expect(phone.get_by_text("All as expected?")).to_be_visible()
        expect(phone.get_by_text("Records: still set, no animal · ready · camera working.")).to_be_visible()
        expect(phone.get_by_role("button", name="Routine check")).to_be_visible()
        for outcome in SIX:
            expect(phone.get_by_role("radio", name=outcome, exact=True)).to_be_visible()
        assert phone.get_by_role("button", name=re.compile(r"^Save check")).count() == 0, "no Save before an outcome is chosen"
        assert phone.get_by_role("button", name=re.compile(r"Exit to Trap sites")).count() == 0, "the legacy pill is gone from this page"
        assert phone.get_by_role("button", name=re.compile(r"Back to trap list")).count() == 1
        expect(phone.get_by_text("Mangaroa Farm · Build 4.3")).to_be_visible()  # site; the generic "Trap 1" is left out; the build because the site compares builds


def test_a_trap_with_no_camera_is_told_so_in_the_routine_card(tmp_path, phone: Page):
    with _serve(tmp_path / "d") as url:
        cf.start_visit_and_open(phone, url, NOCAM)
        expect(phone.get_by_text("Records: still set, no animal · ready.")).to_be_visible()
        assert "camera working" not in phone.locator("body").inner_text()


# ---------------------------------------------------------------- Routine
@pytest.mark.parametrize("trap, cell", [
    (CAM, m._cell("camera_trial", "Trap still set, no animal", "", "Yes", "", "Yes", "", "", False, "", ("", "", "", 0))),
    (NOCAM, m._cell("nocamera_trial", "Trap still set, no animal", "", "Yes", "", "NA", "", "", False, "", ("", "", "", 0))),
], ids=["camera trap", "no-camera trap"])
def test_routine_confirm_screen_and_it_writes_exactly_what_answering_by_hand_writes(trap, cell, tmp_path, phone: Page):
    frozen = _frozen_rows(tmp_path, [cell])[m.cell_key(cell)]["rows"]
    data_dir = tmp_path / "d"
    with _serve(data_dir) as url:
        before = {n: _sheet(data_dir, n) for n in ("Checks", "Windows", "Followups")}
        cf.start_visit_and_open(phone, url, trap)
        phone.get_by_role("button", name="Routine check").click()
        expect(phone.get_by_text("This will record")).to_be_visible()
        expect(phone.get_by_text("Trap still set, no animal")).to_be_visible()
        assert (phone.get_by_text("Camera working and covering").count() == 1) == (trap == CAM)
        expect(phone.get_by_text("Routine check", exact=True)).to_be_visible()
        cf.save_check(phone, 7000)
        checks, windows, followups = (_sheet(data_dir, n) for n in ("Checks", "Windows", "Followups"))
        written = {
            "checks_new": checks.iloc[len(before["Checks"]):].values.tolist(),
            "windows": windows[windows["Trap ID"] == trap].values.tolist(),
            "followups_new": followups.iloc[len(before["Followups"]):].values.tolist(),
        }
        assert len(written["checks_new"]) == 1
        visits = set(checks["Visit ID"].tolist()) | {m.VISIT_ID}
        assert _normalise(written, set(), visits) == _normalise(frozen, set(), visits)


def test_record_something_different_leaves_nothing_ticked(tmp_path, phone: Page):
    with _serve(tmp_path / "d") as url:
        cf.start_visit_and_open(phone, url, CAM)
        phone.get_by_role("button", name="Routine check").click()
        phone.get_by_role("button", name="Record something different").click()
        for outcome in SIX:
            expect(phone.get_by_role("radio", name=outcome, exact=True)).not_to_be_checked()
        cf.pick_finding(phone, "Trap fired, no animal")
        for option in ("Yes", "No", "Could not assess"):
            expect(phone.get_by_role("radiogroup", name="Camera working and covering the trap?").get_by_role("radio", name=option, exact=True)).not_to_be_checked()
        for option in ("Yes", "No"):
            expect(phone.get_by_role("radiogroup", name="Trap relured, reset and ready?").get_by_role("radio", name=option, exact=True)).not_to_be_checked()


# ---------------------------------------------------------------- Change keeps what still applies
def test_change_keeps_the_answers_that_still_apply(tmp_path, phone: Page):
    with _serve(tmp_path / "d") as url:
        cf.start_visit_and_open(phone, url, CAM)
        cf.pick_finding(phone, "Trap still set, no animal")
        cf.pick(phone, "service", "No")
        cf.type_into(phone, "Why is the trap not ready?", "Bait gone")
        cf.pick(phone, "camera", "Yes")
        cf.add_note(phone, "Wasp nest on the post")
        phone.get_by_role("button", name="Change", exact=True).click()
        for outcome in SIX:
            expect(phone.get_by_role("radio", name=outcome, exact=True)).to_be_visible()
        cf.pick_finding(phone, "Trap disturbed")
        expect(phone.get_by_role("radiogroup", name="Trap relured, reset and ready?").get_by_role("radio", name="No", exact=True)).to_be_checked()
        expect(phone.get_by_label("Why is the trap not ready?")).to_have_value("Bait gone")
        expect(phone.get_by_role("radiogroup", name="Camera working and covering the trap?").get_by_role("radio", name="Yes", exact=True)).to_be_checked()
        expect(phone.get_by_label("Notes")).to_have_value("Wasp nest on the post")


@pytest.mark.parametrize("outcome, absent", [("Trap missing", "Trap relured"), ("Unable to check", "Camera working")])
def test_an_unreached_trap_is_asked_no_service_or_camera_question(outcome, absent, tmp_path, phone: Page):
    with _serve(tmp_path / "d") as url:
        cf.start_visit_and_open(phone, url, CAM)
        cf.pick_finding(phone, outcome)
        expect(phone.get_by_role("button", name=re.compile(r"^Save check$"))).to_be_visible()
        body = phone.locator("body").inner_text()
        assert "Trap relured" not in body and "Camera working" not in body
        assert ("Monitoring stops at this trap" in body) == (outcome == "Trap missing")
        assert ("Monitoring carries on with a new window" in body) == (outcome == "Unable to check")


# ---------------------------------------------------------------- errors, and Save's states
def test_a_refused_save_shows_a_summary_and_a_line_at_each_field_and_save_is_not_stuck(tmp_path, phone: Page):
    with _serve(tmp_path / "d") as url:
        cf.start_visit_and_open(phone, url, CAM)
        cf.pick_finding(phone, "Dead animal found")
        cf.pick(phone, "carcass", "Yes")
        cf.pick_condition(phone, "Dead and apparently normal")
        cf.pick(phone, "service", "Yes")
        cf.pick(phone, "camera", "Yes")
        assert "thing" not in " ".join(cf.body_lines(phone, "to finish")), "no errors before a Save has been refused"
        _save_button(phone).click()
        expect(phone.get_by_text("2 things to finish")).to_be_visible()
        expect(phone.get_by_text("Choose the species.").first).to_be_visible()
        expect(phone.get_by_text("Confirm that bag").first).to_be_visible()
        assert phone.get_by_text("Choose the species.").count() == 2, "once in the summary and once under the field"
        assert phone.get_by_role("button", name="Saving check…").count() == 0, "Save is back to Save check, not stuck"
        assert phone.get_by_text("Do not tap again").count() == 0
        expect(phone.get_by_role("button", name=re.compile(r"^Save check$"))).to_be_enabled()
        cf.pick_species(phone, "Rat", "Norway rat")
        expect(phone.get_by_text("1 thing to finish")).to_be_visible()
        assert phone.get_by_text("Choose the species.").count() == 0, "a fixed field's error goes at once"


def test_two_rapid_taps_on_save_write_one_check(tmp_path, phone: Page):
    data_dir = tmp_path / "d"
    with _serve(data_dir) as url:
        cf.start_visit_and_open(phone, url, CAM)
        cf.pick_finding(phone, "Trap still set, no animal")
        cf.pick(phone, "service", "Yes")
        cf.pick(phone, "camera", "Yes")
        button = _save_button(phone)
        button.evaluate("el => { el.click(); el.click(); }")  # two taps in the same instant
        phone.wait_for_timeout(9000)
        assert len(_sheet(data_dir, "Checks")) == 1


def test_save_waits_for_a_photo_that_has_not_finished_uploading(tmp_path, phone: Page):
    data_dir = tmp_path / "d"
    with _serve(data_dir) as url:
        cf.start_visit_and_open(phone, url, CAM)
        cf.pick_finding(phone, "Dead animal found")
        cf.pick(phone, "carcass", "Yes")
        visit_id = _sheet(data_dir, "Visits").iloc[-1]["Visit ID"]
        windows = _sheet(data_dir, "Windows")
        window_id = windows[(windows["Trap ID"] == CAM) & (windows["Status"] == "Open")].iloc[-1]["Window ID"]
        bag = cf.body_lines(phone, "Bag ID:")[0].split(":")[-1].strip()
        context = {"check_id": pi.deterministic_check_id(visit_id, CAM), "visit_id": visit_id, "trap_id": CAM, "site_id": "MAN", "bag_id": bag, "window_id": window_id}
        pi.add_expected_photos(data_dir, context, [{"photo_id": "PHOTO-PENDING-0001", "name": "slow.jpg"}])  # expected, never stored
        cf.pick_species(phone, "Rat", "Norway rat")
        button = phone.get_by_role("button", name="Please wait")
        expect(button).to_be_visible()
        expect(button).to_be_disabled()
        # Its reason, in words: the photo is still going (the caption under the button) or it has failed (its own warning above Save).
        reason = phone.get_by_text("Uploading 1 photo… Save check is available when it finishes.").or_(phone.get_by_text("1 photo could not upload"))
        expect(reason.first).to_be_visible()


# ---------------------------------------------------------------- no active window
def test_a_trap_with_history_and_no_window_asks_when_it_went_back_into_service(tmp_path, phone: Page):
    data_dir = tmp_path / "d"
    with _serve(data_dir, SEED_NO_WINDOW) as url:
        cf.start_visit_and_open(phone, url, "R1-MAN-003")
        expect(phone.get_by_text("This trap has no active test window")).to_be_visible()
        expect(phone.get_by_text("It has earlier history, so enter when it actually went back into service.")).to_be_visible()
        expect(phone.get_by_text("Back in service from")).to_be_visible()
        phone.get_by_role("button", name="Start window and continue").click()
        expect(phone.get_by_text("Enter a reason before starting the window.")).to_be_visible()
        cf.type_into(phone, "Reason", "The window was closed in error")
        phone.get_by_role("button", name="Start window and continue").click()
        expect(phone.get_by_text("All as expected?")).to_be_visible(timeout=20000)
        windows = _sheet(data_dir, "Windows")
        assert ((windows["Trap ID"] == "R1-MAN-003") & (windows["Status"] == "Open")).sum() == 1


def test_a_new_trap_with_no_window_starts_one_from_its_deployment_time(tmp_path, phone: Page):
    data_dir = tmp_path / "d"
    with _serve(data_dir, SEED_NO_WINDOW) as url:
        cf.start_visit_and_open(phone, url, "M1-MAN-004")
        expect(phone.get_by_text("Start it from the recorded deployment time, then carry on with this check.")).to_be_visible()
        phone.get_by_role("button", name="Start window and continue").click()
        expect(phone.get_by_text("Records: still set, no animal")).to_be_visible(timeout=20000)


# ---------------------------------------------------------------- the trap list after a save
def test_the_saved_panel_says_a_necropsy_task_was_added_only_when_one_was(tmp_path, phone: Page):
    data_dir = tmp_path / "d"
    with _serve(data_dir) as url:
        cf.start_visit_and_open(phone, url, CAM)
        cf.pick_finding(phone, "Dead animal found")
        cf.pick(phone, "carcass", "Yes")
        cf.stage_photos(phone, tmp_path, 2)
        cf.pick_species(phone, "Rat", "Norway rat")
        cf.pick_condition(phone, "Dead and apparently normal")
        cf.tick(phone, re.compile(r"Bag labelled"))
        cf.pick(phone, "service", "Yes")
        cf.pick(phone, "camera", "Yes")
        cf.save_check(phone, 6000)
        expect(phone.get_by_text(f"{CAM} saved")).to_be_visible()
        expect(phone.get_by_text("2 photos stored")).to_be_visible()
        expect(phone.get_by_text("A necropsy task was added.")).to_be_visible()
        phone.locator(f'[class*="visit_check_"][class*="_{NOCAM}"] button').click()
        cf.pick_finding(phone, "Trap still set, no animal")
        cf.pick(phone, "service", "Yes")
        cf.save_check(phone, 6000)
        expect(phone.get_by_text(f"{NOCAM} saved")).to_be_visible()
        assert phone.get_by_text("A necropsy task was added.").count() == 0


# ---------------------------------------------------------------- desktop
def test_on_desktop_the_form_is_one_column_capped_at_760_and_save_is_its_natural_width(tmp_path, page: Page):
    page.set_viewport_size({"width": 1280, "height": 900})
    with _serve(tmp_path / "d") as url:
        cf.start_visit_and_open(page, url, CAM)
        cf.pick_finding(page, "Trap still set, no animal")
        cf.pick(page, "service", "Yes")
        cf.pick(page, "camera", "Yes")
        column = page.locator('[class*="st-key-r1_screen"], [class*="st-key-screen"]').first.bounding_box()
        save = _save_button(page).bounding_box()
        assert column["width"] <= 761, column
        assert 100 < save["width"] < 460, f"Save is its natural width on desktop, not the column's: {save}"


# ---------------------------------------------------------------- merge-safe drafts: answers of an outcome that no longer applies
def test_answers_from_an_outcome_that_no_longer_applies_do_not_reach_the_record(tmp_path, phone: Page):
    """Switch from a kill (species, rat type, condition, bag, a service 'No' with a reason, a camera problem) to Trap still set, answer that,
    save, and the rows are exactly those of a clean Trap still set: nothing from the kill is written (the draft may still hold it)."""
    from test_check_save_golden_ui import _normalise  # noqa: PLC0415
    cell = m._cell("camera_trial", "Trap still set, no animal", "", "Yes", "", "Yes", "", "", False, "", ("", "", "", 0))
    frozen = _frozen_rows(tmp_path, [cell])[m.cell_key(cell)]["rows"]
    data_dir = tmp_path / "d"
    with _serve(data_dir) as url:
        before = {n: _sheet(data_dir, n) for n in ("Checks", "Windows", "Followups")}
        cf.start_visit_and_open(phone, url, CAM)
        cf.pick_finding(phone, "Dead animal found")
        cf.pick(phone, "carcass", "Yes")
        cf.pick_species(phone, "Rat", "Ship rat")
        cf.pick_condition(phone, "Alive and maimed")
        cf.tick(phone, re.compile(r"Bag labelled"))
        cf.pick(phone, "service", "No")
        cf.type_into(phone, "Why is the trap not ready?", "Lure gone")
        cf.pick(phone, "camera", "No")
        cf.pick(phone, "Camera issue", "Battery low")
        cf.pick(phone, "Camera still covers the trap?", "No")
        cf.tick(phone, "Camera adjusted")
        cf.pick_finding(phone, "Trap still set, no animal")   # Change, then the other outcome: the kill's answers come back from the draft
        cf.pick(phone, "service", "Yes")
        cf.pick(phone, "camera", "Yes")
        cf.save_check(phone, 7000)
        checks, windows, followups = (_sheet(data_dir, n) for n in ("Checks", "Windows", "Followups"))
        written = {
            "checks_new": checks.iloc[len(before["Checks"]):].values.tolist(),
            "windows": windows[windows["Trap ID"] == CAM].values.tolist(),
            "followups_new": followups.iloc[len(before["Followups"]):].values.tolist(),
        }
        assert len(written["checks_new"]) == 1
        visits = set(checks["Visit ID"].tolist()) | {m.VISIT_ID}
        assert _normalise(written, set(), visits) == _normalise(frozen, set(), visits), "the record is a clean Trap still set"
        assert cf.pending_files(data_dir) == [], "and its draft is cleared by the save"
