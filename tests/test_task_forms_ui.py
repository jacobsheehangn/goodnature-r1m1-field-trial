"""Part B batch 1, the UI half (boards B1Cam*, B1CamIssue*, B1TrapNotReady*): the Camera review, Camera issue and Trap not ready task pages.

One frame for all three (back pill, title, context card, errors as on the check form, Save), the questions as the boards draw them, and the writes the logic
tests already hold: a Camera review writes what apply_camera_review writes; a hardware task with its trap ready restarts the trap in the same write; one whose
trap is not ready keeps the task open with the note. Local test data only (tests/b1_seed.py)."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
import task_form as tf  # noqa: E402
from b1_seed import ALREADY_RESTARTED, B1_SEED, OTHER_TASK_OPEN  # noqa: E402
from test_check_save_golden_ui import _serve  # noqa: E402
from test_trial_model_ui import _sheet  # noqa: E402

KILL, FIRED, ISSUE, SERVICE = "R1-MAN-001", "R1-MAN-005", "R1-MAN-002", "R1-MAN-003"


def _days_ago(days: int, hour: int, minute: int) -> datetime:
    return (datetime.now() - timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def _row(data_dir: Path, sheet: str, column: str, value: str) -> pd.Series:
    frame = _sheet(data_dir, sheet)
    return frame[frame[column] == value].iloc[0]


def _task(data_dir: Path, kind: str, trap: str) -> pd.Series:
    frame = _sheet(data_dir, "Followups")
    return frame[(frame["Follow-up Type"] == kind) & (frame["Trap ID"] == trap)].iloc[0]


def _open_windows(data_dir: Path, trap: str) -> pd.DataFrame:
    frame = _sheet(data_dir, "Windows")
    return frame[(frame["Trap ID"] == trap) & (frame["Status"] == "Open")]


def _kill_review(page: Page, url: str) -> None:
    tf.open_task(page, url, "Camera review", KILL)


# --- Camera review ----------------------------------------------------------------------------------------------------------

def test_a_kill_review_has_the_boards_frame_asks_what_a_confirmed_kill_needs_and_writes_the_golden_rows(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, B1_SEED) as url:
        _kill_review(page, url)
        assert page.locator('[role="heading"][aria-level="1"]').all_inner_texts() == ["Camera review"]
        expect(page.get_by_role("button", name="Back to task list")).to_be_visible()
        card = page.locator('[class*="st-key-card_task_context"]').inner_text()
        for kept in ("Trap", KILL, "Site", "Bag ID", "MAN-001", "Evidence period"):
            assert kept in card, (kept, card)
        expect(page.get_by_text("Record when things happened in the footage, not when you watched it.", exact=True)).to_be_visible()
        assert page.get_by_text("Complete this review").count() == 0 and page.get_by_text("Task context").count() == 0, "the old headings are gone"
        # Nothing answered: one question, and Save says what is missing, once, at the field and above Save.
        tf.choose(page, "Camera evidence usable?", "Yes")
        expect(page.get_by_text("Confirmed kill: target interaction, entry to the strike area and activation are already recorded.", exact=True)).to_be_visible()
        assert page.get_by_text("Target animal interaction visible?").count() == 0, "a confirmed kill is not asked what the kill already says"
        save = page.get_by_role("button", name="Save camera review", exact=True)
        save.click()
        expect(page.get_by_text("4 things to finish", exact=True)).to_be_visible(timeout=15_000)
        expect(save).to_be_enabled(timeout=15_000)
        assert save.inner_text().strip() == "Save camera review", "never left on Saving… after a refusal"
        summary = page.locator(".r1-msg.error").inner_text()
        for words in ("Choose the interaction level.", "Enter the first target interaction date and time.", "Enter the kill date and time.", "Choose the video humane-kill indicator."):
            assert page.locator(".r1-fielderr").filter(has_text=words).count() == 1, f"{words!r} at its field"
            assert words in summary, f"{words!r} in the summary above Save"
        assert page.locator('[class*="st-key-fielderr_level_"],[class*="st-key-fielderr_first_"],[class*="st-key-fielderr_kill_"],[class*="st-key-fielderr_assessment_"]').count() == 4
        # They update live: answering a question takes its line away.
        tf.choose(page, "Interaction level", "Repeated interaction")
        expect(page.get_by_text("3 things to finish", exact=True)).to_be_visible(timeout=15_000)
        first, kill = _days_ago(4, 21, 47), _days_ago(4, 22, 3)
        tf.set_when(page, "first", first)
        tf.set_when(page, "kill", kill)
        tf.choose(page, "Video humane-kill indicator", "Humane")
        expect(page.get_by_text("things to finish")).to_have_count(0, timeout=15_000)
        tf.type_into(page, "Video link", "drive.example/clip-0142")
        tf.save(page, "Save camera review")
        expect(page.get_by_text("Camera review saved", exact=True)).to_be_visible(timeout=60_000)
        expect(page.get_by_text("Interaction to kill: 16", exact=False)).to_be_visible()
    window = _row(data_dir, "Windows", "Window ID", "W-KILL-1")
    assert (window["Evidence Usable"], window["Interaction Level"], window["Entered Strike Area"], window["Trap Activated"], window["Video Assessment"]) == (
        "Yes", "Repeated interaction", "Yes", "Yes", "Humane")
    assert window["First Interaction Time"] == first.strftime("%Y-%m-%d %H:%M:%S") and window["Kill Time"] == kill.strftime("%Y-%m-%d %H:%M:%S")
    assert window["Video Link"] == "drive.example/clip-0142" and window["Review Status"] == "Complete"
    assert _task(data_dir, "Camera review", KILL)["Status"] == "Complete"


def test_a_review_of_a_trap_that_fired_asks_each_question_only_when_the_answer_before_it_makes_it_apply(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, B1_SEED) as url:
        tf.open_task(page, url, "Camera review", FIRED)
        assert page.get_by_text("Bag ID").count() == 0, "no bag: the fuller form"
        tf.choose(page, "Camera evidence usable?", "Yes")
        expect(page.get_by_text("Target animal interaction visible?", exact=True)).to_be_visible()
        assert page.get_by_text("Interaction level", exact=True).count() == 0 and page.get_by_text("Entered the strike area?").count() == 0
        tf.choose(page, "Target animal interaction visible?", "Yes")
        tf.choose(page, "Interaction level", "Single interaction")
        expect(page.get_by_text("Entered the strike area?", exact=True)).to_be_visible()
        assert page.get_by_text("Trap activated?").count() == 0
        tf.choose(page, "Entered the strike area?", "No")
        expect(page.get_by_text("Activation is not applicable because meaningful entry did not occur.", exact=True)).to_be_visible()
        assert page.get_by_text("Trap activated?").count() == 0, "no activation question when the animal did not enter"
        tf.choose(page, "Entered the strike area?", "Yes")
        tf.choose(page, "Trap activated?", "Yes")
        expect(page.get_by_text("First activation", exact=True)).to_be_visible()
        first, trigger = _days_ago(5, 2, 11), _days_ago(5, 2, 12)
        tf.set_when(page, "first", first)
        tf.set_when(page, "trigger", trigger)
        tf.save(page, "Save camera review")
        expect(page.get_by_text("Camera review saved", exact=True)).to_be_visible(timeout=60_000)
        expect(page.get_by_text("No interaction-to-kill time recorded.", exact=True)).to_be_visible()
    window = _row(data_dir, "Windows", "Window ID", "W-FIRE-1")
    assert (window["Evidence Usable"], window["Target Present"], window["Entered Strike Area"], window["Trap Activated"], window["Activation Evidence"]) == (
        "Yes", "Yes", "Yes", "Yes", "Observed")
    assert window["Trigger Time"] == trigger.strftime("%Y-%m-%d %H:%M:%S")


def test_evidence_that_is_not_usable_asks_for_no_times_and_a_time_outside_the_window_is_refused_with_its_edge(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, B1_SEED) as url:
        _kill_review(page, url)
        tf.choose(page, "Camera evidence usable?", "Yes")
        tf.choose(page, "Interaction level", "Single interaction")
        tf.choose(page, "Video humane-kill indicator", "Humane")
        tf.set_when(page, "first", _days_ago(4, 21, 47))
        tf.set_when(page, "kill", _days_ago(4, 21, 30))
        tf.save(page, "Save camera review")
        expect(page.get_by_text("Kill time can't be before the first interaction.", exact=True)).to_have_count(2, timeout=15_000)
        assert _task(data_dir, "Camera review", KILL)["Status"] == "Open", "nothing was written"
        tf.choose(page, "Camera evidence usable?", "No")
        expect(page.get_by_text("No event times needed", exact=True)).to_be_visible()
        assert page.locator('[data-testid="stDateInput"]').count() == 0
        tf.type_into(page, "Notes", "Camera battery flat from 8 Oct.")
        tf.save(page, "Save camera review")
        expect(page.get_by_text("Camera review saved", exact=True)).to_be_visible(timeout=60_000)
    window = _row(data_dir, "Windows", "Window ID", "W-KILL-1")
    assert (window["Evidence Usable"], window["Video Assessment"]) == ("No", "No usable video")
    assert _task(data_dir, "Camera review", KILL)["Notes"] == "Camera battery flat from 8 Oct."


# --- Camera issue -----------------------------------------------------------------------------------------------------------

def _answer_camera_issue(page: Page, outcome: str, ready: str, evidence: str) -> None:
    tf.choose(page, "Camera outcome", outcome)
    tf.choose(page, "Camera now ready and covering the trap?", ready)
    tf.choose(page, "Past test-window evidence", evidence)


def test_a_camera_issue_shows_what_the_check_found_and_restarts_the_trap_from_the_time_chosen(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, B1_SEED) as url:
        tf.open_task(page, url, "Camera issue", ISSUE)
        card = page.locator('[class*="st-key-card_task_context"]').inner_text()
        for kept in ("Reported at the check", "Battery low", "Camera still covered the trap", "Yes", "Checked", "08:40"):
            assert kept in card, (kept, card)
        assert page.get_by_text("Back in service from").count() == 0, "asked only once the camera is ready"
        _answer_camera_issue(page, "Fixed and now working", "Yes", "Still usable")
        expect(page.get_by_text("Back in service from", exact=True)).to_be_visible()
        expect(page.get_by_text("Saving closes this task, records the camera's state and past evidence, and restarts " + ISSUE + ".", exact=True)).to_be_visible()
        tf.type_into(page, "Resolution notes", "Swapped battery, checked the view.")
        # Before the check that took it out: refused, in the boards' words, nothing written.
        tf.set_when(page, "when", _days_ago(3, 16, 0))
        tf.save(page, "Save camera resolution")
        expect(page.get_by_text("Back in service can't be before the check that took it out (", exact=False)).to_have_count(2, timeout=15_000)
        assert _task(data_dir, "Camera issue", ISSUE)["Status"] == "Open" and _open_windows(data_dir, ISSUE).empty
        back = _days_ago(1, 10, 5)
        tf.set_when(page, "when", back)
        tf.save(page, "Save camera resolution")
        expect(page.get_by_text("Camera resolution saved", exact=True)).to_be_visible(timeout=60_000)
        expect(page.get_by_text(f"{ISSUE} is back in service from {back.day} {back:%b}, 10:05.", exact=True)).to_be_visible()
    task = _task(data_dir, "Camera issue", ISSUE)
    assert task["Status"] == "Complete" and task["Notes"].startswith("Fixed and now working. Camera ready: Yes. Past evidence: Still usable.")
    opened = _open_windows(data_dir, ISSUE)
    assert len(opened) == 1 and opened.iloc[0]["Start Time"] == back.strftime("%Y-%m-%d %H:%M:%S"), "the trap restarted from the time chosen"


def test_a_camera_that_is_not_ready_keeps_the_task_open_with_the_note_and_the_trap_out_of_service(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, B1_SEED) as url:
        tf.open_task(page, url, "Camera issue", ISSUE)
        tf.choose(page, "Camera outcome", "Could not fix")
        tf.choose(page, "Camera now ready and covering the trap?", "Yes")
        tf.choose(page, "Past test-window evidence", "Not usable")
        tf.type_into(page, "Resolution notes", "Camera won't power on. Needs a replacement unit.")
        tf.save(page, "Save camera resolution")
        expect(page.get_by_text("2 things to finish", exact=True)).to_be_visible(timeout=15_000)
        expect(page.locator(".r1-fielderr").filter(has_text="A camera that could not be fixed cannot be marked ready.")).to_have_count(1)
        tf.choose(page, "Camera now ready and covering the trap?", "No")
        expect(page.locator(".r1-msg.error")).to_have_count(0, timeout=15_000)  # not ready asks for no time, and the rule no longer applies
        expect(page.get_by_text(f"{ISSUE} stays out of service", exact=True)).to_be_visible()
        expect(page.get_by_text("Saving adds your note and the past-evidence answer. Nothing restarts.", exact=True)).to_be_visible()
        assert page.get_by_text("Back in service from").count() == 0
        tf.save(page, "Save note, keep task open")
        expect(page.get_by_text("Note added", exact=True)).to_be_visible(timeout=60_000)
        expect(page.get_by_text(f"{ISSUE} is still awaiting service.", exact=True)).to_be_visible()
    task = _task(data_dir, "Camera issue", ISSUE)
    assert task["Status"] == "Open" and "Camera won't power on. Needs a replacement unit." in task["Notes"]
    assert _open_windows(data_dir, ISSUE).empty, "nothing restarted"
    assert _row(data_dir, "Windows", "Trap ID", ISSUE)["Evidence Usable"] == "No", "the past-evidence answer was still applied"


def test_a_task_whose_trap_cannot_restart_says_why_and_asks_for_no_time(page: Page, tmp_path: Path) -> None:
    for name, extra, title, detail in (
        ("other", OTHER_TASK_OPEN, "Camera issue is still open for " + SERVICE, "Its test window starts when that task is done too."),
        ("back", ALREADY_RESTARTED, ISSUE + " is already back in service", "Nothing to restart."),
    ):
        data_dir = tmp_path / name; data_dir.mkdir()
        page.set_viewport_size({"width": 390, "height": 844})
        seed = B1_SEED + extra
        with _serve(data_dir, seed) as url:
            kind, trap = ("Trap not ready", SERVICE) if name == "other" else ("Camera issue", ISSUE)
            tf.open_task(page, url, kind, trap)
            if name == "other":
                tf.choose(page, "Trap now relured, reset and ready?", "Yes")
            else:
                _answer_camera_issue(page, "Replaced", "Yes", "Partly usable")
            expect(page.get_by_text(title, exact=True)).to_be_visible(timeout=15_000)
            expect(page.get_by_text(detail, exact=False)).to_be_visible()
            assert page.get_by_text("Back in service from").count() == 0, "nothing to restart: no time asked"
            tf.type_into(page, "What was done?" if name == "other" else "Resolution notes", "Done.")
            tf.save(page, "Save trap service" if name == "other" else "Save camera resolution")
            expect(page.get_by_text("Trap service saved" if name == "other" else "Camera resolution saved", exact=True)).to_be_visible(timeout=60_000)
        assert _task(data_dir, kind, trap)["Status"] == "Complete", "the task still closes"
        before = 1 if name == "back" else 0
        assert len(_open_windows(data_dir, trap)) == before, "and no second window starts"


# --- Trap not ready ---------------------------------------------------------------------------------------------------------

def test_a_trap_not_ready_task_restarts_the_trap_when_it_is_ready_and_never_touches_the_windows_evidence(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, B1_SEED) as url:
        tf.open_task(page, url, "Trap not ready", SERVICE)
        card = page.locator('[class*="st-key-card_task_context"]').inner_text()
        for kept in ("Reason given at the check", "Spring weak, wouldn't reset", "Checked"):
            assert kept in card, (kept, card)
        assert page.get_by_role("radiogroup", name="Camera outcome").count() == 0, "a trap task is never shown the camera form"
        evidence_before = _row(data_dir, "Windows", "Trap ID", SERVICE)["Evidence Usable"]
        tf.choose(page, "Trap now relured, reset and ready?", "Yes")
        expect(page.get_by_text("Back in service from", exact=True)).to_be_visible()
        tf.save(page, "Save trap service")
        expect(page.get_by_text("2 things to finish", exact=True)).to_be_visible(timeout=15_000)
        expect(page.locator(".r1-fielderr").filter(has_text="Enter when the trap was back in service.")).to_have_count(1)
        expect(page.locator(".r1-fielderr").filter(has_text="Say what was done.")).to_have_count(1)
        back = _days_ago(1, 9, 40)
        tf.set_when(page, "when", back)
        tf.type_into(page, "What was done?", "Replaced the spring and relured.")
        tf.save(page, "Save trap service")
        expect(page.get_by_text("Trap service saved", exact=True)).to_be_visible(timeout=60_000)
    task = _task(data_dir, "Trap not ready", SERVICE)
    assert task["Status"] == "Complete" and task["Notes"] == "Replaced the spring and relured."
    opened = _open_windows(data_dir, SERVICE)
    assert len(opened) == 1 and opened.iloc[0]["Start Time"] == back.strftime("%Y-%m-%d %H:%M:%S")
    closed = _sheet(data_dir, "Windows")
    assert closed[(closed["Trap ID"] == SERVICE) & (closed["Status"] == "Closed")].iloc[0]["Evidence Usable"] == evidence_before


def test_a_trap_that_is_not_ready_keeps_its_task_open_and_asks_what_was_found(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, B1_SEED) as url:
        tf.open_task(page, url, "Trap not ready", SERVICE)
        tf.choose(page, "Trap now relured, reset and ready?", "No")
        expect(page.get_by_text("What did you find?", exact=True)).to_be_visible()
        expect(page.get_by_text(f"{SERVICE} stays out of service", exact=True)).to_be_visible()
        expect(page.get_by_text("Saving adds your note. Nothing restarts.", exact=True)).to_be_visible()
        tf.save(page, "Save note, keep task open")
        expect(page.get_by_text("Say what you found.", exact=True)).to_have_count(2, timeout=15_000)
        tf.type_into(page, "What did you find?", "Needs a new spring. Ordered.")
        tf.save(page, "Save note, keep task open")
        expect(page.get_by_text("Note added", exact=True)).to_be_visible(timeout=60_000)
        expect(page.get_by_text(f"{SERVICE} is still awaiting service.", exact=True)).to_be_visible()
        # The task is still on the list, and a second note is added to the first.
        page.locator('[class*="st-key-listrow_"]').filter(has_text="Trap not ready").get_by_role("button", name="Review", exact=True).click()
        tf.choose(page, "Trap now relured, reset and ready?", "No")
        tf.type_into(page, "What did you find?", "Spring arrived, fitting it Friday.")
        tf.save(page, "Save note, keep task open")
        expect(page.get_by_text("Note added", exact=True)).to_be_visible(timeout=60_000)
    task = _task(data_dir, "Trap not ready", SERVICE)
    lines = task["Notes"].split("\n")
    assert task["Status"] == "Open" and len(lines) == 2 and lines[0].endswith("· Needs a new spring. Ordered.") and lines[1].endswith("· Spring arrived, fitting it Friday.")
    assert _open_windows(data_dir, SERVICE).empty


# --- The frame, on a phone and on desktop ------------------------------------------------------------------------------------

def test_every_task_page_is_one_column_with_a_save_that_fills_a_phone_and_keeps_its_natural_width_on_desktop(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, B1_SEED) as url:
        for width, kind, trap, save in ((390, "Camera review", KILL, "Save camera review"), (390, "Camera issue", ISSUE, "Save camera resolution"),
                                        (390, "Trap not ready", SERVICE, "Save trap service")):
            page.set_viewport_size({"width": width, "height": 844})
            tf.open_task(page, url, kind, trap)
            button = page.get_by_role("button", name=save, exact=True).bounding_box()
            assert button["width"] >= 390 - 40, (kind, button)
            assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"), f"{kind}: no sideways scroll on a phone"
            page.get_by_role("button", name="Back to task list").click()
            expect(page.get_by_role("heading", name="Follow-ups", exact=True)).to_be_visible(timeout=20_000)
        page.set_viewport_size({"width": 1280, "height": 900})
        tf.open_task(page, url, "Trap not ready", SERVICE)
        screen = page.locator(".st-key-r1_screen").bounding_box()
        assert screen["width"] <= 761, f"one 760px column on desktop: {screen}"
        button = page.get_by_role("button", name="Save trap service", exact=True).bounding_box()
        assert button["width"] <= 300, f"Save keeps its natural width on desktop: {button}"
