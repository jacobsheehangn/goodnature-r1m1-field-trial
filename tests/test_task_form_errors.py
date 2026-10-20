"""Batch 1: what each task form still needs (camera_review_errors, camera_issue_errors, trap_service_errors), as (field, words) in the order the form asks.

Pure functions, so no browser: the words are the boards' (B1CamErrors, B1CamIssueErrors, B1TrapNotReadyErrors), a form never complains about an answer it no
longer shows, and a range error names the moment it is held against."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = """
    import json
    from datetime import date, datetime, time, timedelta
    import app
    NOW = datetime(2026, 10, 12, 9, 0)
    START, END = datetime(2026, 10, 6, 9, 15), datetime(2026, 10, 12, 8, 40)
    D = lambda day, hh=0, mm=0: (date(2026, 10, day), time(hh, mm))
    def review(**kw):
        base = dict(is_kill_review=False, usable=None, target=None, level=None, strike=None, activated=None, assessment=None,
                    first_d=None, first_t=None, trigger_d=None, trigger_t=None, kill_d=None, kill_t=None, window_start=START, window_end=END)
        base.update(kw)
        return [list(e) for e in app.camera_review_errors(**base)]
    def at(prefix, day, hh, mm):
        return {prefix + "_d": date(2026, 10, day), prefix + "_t": time(hh, mm)}
    out = {}
    out["nothing"] = review()
    out["usable_no"] = review(usable="No")
    out["usable_no_ignores_stale"] = review(usable="No", target="Yes", level=None, strike="Yes")
    out["full_nothing_answered"] = review(usable="Yes")
    out["target_no"] = review(usable="Yes", target="No")
    out["target_unclear"] = review(usable="Yes", target="Unclear")
    out["target_yes"] = review(usable="Yes", target="Yes")
    out["strike_yes"] = review(usable="Yes", target="Yes", level="Single interaction", strike="Yes", **at("first", 9, 2, 11))
    out["strike_no"] = review(usable="Yes", target="Yes", level="Single interaction", strike="No", **at("first", 9, 2, 11))
    out["activated_yes"] = review(usable="Yes", target="Yes", level="Single interaction", strike="Yes", activated="Yes", **at("first", 9, 2, 11))
    out["all_done"] = review(usable="Yes", target="Yes", level="Single interaction", strike="Yes", activated="Yes", **at("first", 9, 2, 11), **at("trigger", 9, 2, 12))
    out["kill_nothing"] = review(is_kill_review=True, usable="Yes")
    out["kill_done"] = review(is_kill_review=True, usable="Yes", level="Repeated interaction", assessment="Humane", **at("first", 10, 21, 47), **at("kill", 10, 22, 3))
    out["kill_before_first"] = review(is_kill_review=True, usable="Yes", level="Repeated interaction", **at("first", 10, 21, 47), **at("kill", 10, 21, 30))
    out["before_window"] = review(is_kill_review=True, usable="Yes", level="Single interaction", assessment="Humane", **at("first", 5, 21, 47), **at("kill", 10, 22, 3))
    out["after_window"] = review(is_kill_review=True, usable="Yes", level="Single interaction", assessment="Humane", **at("first", 10, 21, 47), **at("kill", 13, 1, 0))
    out["activation_before_first"] = review(usable="Yes", target="Yes", level="Single interaction", strike="Yes", activated="Yes", **at("first", 9, 2, 11), **at("trigger", 9, 2, 5))
    out["half_a_moment"] = review(usable="Yes", target="Yes", level="Single interaction", strike="No", first_d=date(2026, 10, 9))
    out["open_window"] = review(is_kill_review=True, usable="Yes", level="Single interaction", assessment="Humane", window_end=None, **at("first", 10, 21, 47), **at("kill", 30, 1, 0))
    def issue(**kw):
        base = dict(resolution=None, ready=None, past_evidence=None, notes="", restart_error=None)
        base.update(kw)
        return [list(e) for e in app.camera_issue_errors(**base)]
    out["issue_nothing"] = issue()
    out["issue_done_ready"] = issue(resolution="Fixed and now working", ready="Yes", past_evidence="Still usable", notes="Swapped battery.")
    out["issue_could_not_fix_ready"] = issue(resolution="Could not fix", ready="Yes", past_evidence="Still usable", notes="x")
    out["issue_could_not_fix_not_ready"] = issue(resolution="Could not fix", ready="No", past_evidence="Not usable", notes="x")
    out["issue_time"] = issue(resolution="Replaced", ready="Yes", past_evidence="Partly usable", notes="", restart_error="Back in service can't be in the future.")
    def service(**kw):
        base = dict(ready=None, notes="", restart_error=None)
        base.update(kw)
        return [list(e) for e in app.trap_service_errors(**base)]
    out["service_nothing"] = service()
    out["service_yes_empty"] = service(ready="Yes", restart_error="Enter when the trap was back in service.")
    out["service_yes_done"] = service(ready="Yes", notes="Replaced the spring.")
    out["service_no_empty"] = service(ready="No")
    out["service_no_done"] = service(ready="No", notes="Needs a new spring.")
    out["when"] = [app.task_when(START), app.task_when(datetime(2026, 10, 2, 0, 5)), app.task_when("")]
    print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> dict:
    data_dir = tmp_path_factory.mktemp("errs") / "d"; data_dir.mkdir()
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir),
               PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "tests")]))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"stdout={r.stdout[-1500:]}\nstderr={r.stderr[-3500:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])


def fields(errors) -> list:
    return [f for f, _ in errors]


def test_moments_are_written_the_way_the_boards_write_them(out):
    assert out["when"] == ["6 Oct, 09:15", "2 Oct, 00:05", "—"]


def test_a_camera_review_with_nothing_answered_asks_only_whether_the_evidence_is_usable(out):
    assert out["nothing"] == [["usable", "Say whether the camera evidence is usable."]]


def test_not_usable_asks_nothing_more_and_ignores_answers_the_form_no_longer_shows(out):
    assert out["usable_no"] == [] and out["usable_no_ignores_stale"] == []


def test_the_questions_follow_the_answers_in_the_order_the_form_asks(out):
    assert fields(out["full_nothing_answered"]) == ["target"]
    assert out["target_no"] == [] and out["target_unclear"] == []
    assert fields(out["target_yes"]) == ["level", "first", "strike"]
    assert fields(out["strike_yes"]) == ["activated"]
    assert out["strike_no"] == [], "no activation question when the animal did not enter"
    assert fields(out["activated_yes"]) == ["trigger"]
    assert out["all_done"] == []


def test_a_confirmed_kill_asks_the_level_the_first_interaction_the_kill_and_the_indicator(out):
    assert fields(out["kill_nothing"]) == ["level", "first", "kill", "assessment"]
    assert out["kill_done"] == []
    assert out["kill_nothing"][3] == ["assessment", "Choose the video humane-kill indicator."]


def test_a_kill_before_the_first_interaction_is_refused_in_the_boards_words(out):
    assert out["kill_before_first"] == [["kill", "Kill time can't be before the first interaction."], ["assessment", "Choose the video humane-kill indicator."]]


def test_a_time_outside_the_evidence_period_names_the_edge_it_is_held_against(out):
    assert out["before_window"] == [["first", "First interaction time can't be before the window started (6 Oct, 09:15)."]]
    assert out["after_window"] == [["kill", "Kill time can't be after the check closed the window (12 Oct, 08:40)."]]
    assert out["activation_before_first"] == [["trigger", "Activation time can't be before the first interaction."]]


def test_a_date_without_its_time_is_asked_for_in_full_and_an_open_window_has_no_end_to_pass(out):
    assert out["half_a_moment"] == [["first", "Enter the first target interaction date and time."]]
    assert out["open_window"] == [], "a window with no end time has nothing to be after"


def test_a_camera_issue_asks_for_the_outcome_the_readiness_the_evidence_and_a_note(out):
    assert fields(out["issue_nothing"]) == ["resolution", "ready", "evidence", "notes"]
    assert out["issue_done_ready"] == []
    assert out["issue_time"] == [["when", "Back in service can't be in the future."], ["notes", "Add a short resolution note."]]


def test_a_camera_that_could_not_be_fixed_cannot_be_marked_ready(out):
    assert out["issue_could_not_fix_ready"] == [["ready", "A camera that could not be fixed cannot be marked ready."]]
    assert out["issue_could_not_fix_not_ready"] == [], "not ready is allowed: the task stays open"


def test_a_trap_not_ready_task_asks_for_what_the_chosen_answer_needs(out):
    assert out["service_nothing"] == [["ready", "Say whether the trap is now relured, reset and ready."]], "no note is asked for before an answer is chosen"
    assert out["service_yes_empty"] == [["when", "Enter when the trap was back in service."], ["notes", "Say what was done."]]
    assert out["service_yes_done"] == []
    assert out["service_no_empty"] == [["notes", "Say what you found."]]
    assert out["service_no_done"] == []
