"""Batch 1 (boards B1CamIssue*, B1TrapNotReady*): completing a Trap not ready or Camera issue task restarts the trap, or keeps the task open.

Logic only (no browser): complete_hardware_task() starts the trap's new window at "Back in service from" in the same single write that completes the task
(stamped with the site's open trial, with an audit row), refuses a time before the check that took the trap out or in the future, starts no window when another
hardware task is still open, a check has already restarted the trap, or the trap is no longer Active (the task still closes), and writes nothing when anything
raises. keep_hardware_task_open() appends a dated note, keeps the task Open, applies a Camera issue's past-evidence answer, and leaves the trap "awaiting
service" rather than a defect."""
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
    import json, copy
    from datetime import timedelta
    import app, check_save_matrix as m
    NOW = m.PINNED_NOW
    END = NOW - timedelta(hours=3)          # the check that took the trap out closed its window then
    out = {}
    with m.Pinned(app) as pin:
        saves = []
        app.save_data = lambda d: saves.append(1)          # no disk: the writes are checked on the frames

        def fixture(extra_task=False, window_open=False, inactive=False):
            pin.reset(0)
            data = app.create_sample_data()
            app.create_trial(data, "MAN", ["R1 · R1 Build 4.3"], NOW - timedelta(days=3))
            idx = data["Windows"].index[data["Windows"]["Trap ID"] == "R1-MAN-001"][0]
            for k, v in {"Start Time": app.dtstr(NOW - timedelta(days=1)), "End Time": app.dtstr(END), "Status": "Closed", "Finding At Close": "Trap still set, no animal", "Review Status": "Open"}.items():
                data["Windows"].at[idx, k] = v
            wid = data["Windows"].at[idx, "Window ID"]
            app.add_followup(data, "Trap not ready", "MAN", "R1-MAN-001", "V1", wid, "", "Lure gone", "Restore the trap to service", "High")
            app.add_followup(data, "Camera issue", "MAN", "R1-MAN-001", "V1", wid, "", "Camera issue", "Resolve camera condition", "High")
            if window_open:
                app.start_window(data, "R1-MAN-001", END + timedelta(minutes=5))
            if inactive:
                data["Traps"].loc[data["Traps"]["Trap ID"] == "R1-MAN-001", "Status"] = "Inactive"
            tasks = {r["Follow-up Type"]: r for _, r in data["Followups"].iterrows()}
            if not extra_task:
                data["Followups"] = data["Followups"][data["Followups"]["Follow-up Type"] == "Trap not ready"].reset_index(drop=True)
                tasks = {"Trap not ready": data["Followups"].iloc[0]}
            return data, tasks, wid

        def snapshot(d):
            return {k: v.copy(deep=True) for k, v in d.items()}
        def same(a, b):
            return all(a[k].equals(b[k]) for k in a)
        def win_rows(d):
            w = d["Windows"]; return w[w["Trap ID"] == "R1-MAN-001"][["Window ID", "Start Time", "End Time", "Status", "Trial ID", "Evidence Usable", "Review Status"]].astype(str).values.tolist()

        # S1: Camera issue, restart; Trap not ready is also open, so the first save cannot restart, the second one does (whichever closes last)
        data, tasks, wid = fixture(extra_task=True)
        before = snapshot(data); back = END + timedelta(hours=1); saves.clear()
        r1 = app.complete_hardware_task(data, tasks["Camera issue"], notes="Battery replaced.", back_in_service=back, evidence_gap="Still usable")
        out["s1_first"] = {"result": r1, "saves": len(saves), "windows": win_rows(data), "status": data["Followups"].set_index("Follow-up Type").loc["Camera issue", "Status"]}
        r2 = app.complete_hardware_task(data, tasks["Trap not ready"], notes="Relured and reset.", back_in_service=back, evidence_gap=None)
        audit = data["Audit Log"]; audit = audit[audit["Field"] == "Active test window"]
        out["s1_second"] = {"result": r2, "saves": len(saves), "windows": win_rows(data), "audit": audit[["Record ID", "New Value", "Reason"]].astype(str).values.tolist(),
                            "completed": data["Followups"]["Status"].tolist(), "notes": data["Followups"]["Notes"].tolist(), "when": data["Windows"][data["Windows"]["Window ID"] == r2["window_id"]]["Start Time"].tolist()}
        # S2: Trap not ready alone: restarts; the reviewed window's Evidence Usable is never written
        data, tasks, wid = fixture(); saves.clear()
        ev_before = data["Windows"][data["Windows"]["Window ID"] == wid]["Evidence Usable"].tolist()
        r = app.complete_hardware_task(data, tasks["Trap not ready"], notes="Relured.", back_in_service=END + timedelta(hours=1))
        out["s2"] = {"result": r, "saves": len(saves), "evidence_before": ev_before, "evidence_after": data["Windows"][data["Windows"]["Window ID"] == wid]["Evidence Usable"].tolist(),
                     "trial_ids": data["Windows"][data["Windows"]["Window ID"] == r["window_id"]]["Trial ID"].tolist(), "audit": data["Audit Log"].iloc[-1]["Reason"]}
        # S3: refusals of the restart (the task still closes)
        data, tasks, wid = fixture(window_open=True); saves.clear()
        r = app.complete_hardware_task(data, tasks["Trap not ready"], notes="Done.", back_in_service=END + timedelta(hours=1))
        out["s3_has_window"] = {"result": r, "open_windows": int(((data["Windows"]["Trap ID"] == "R1-MAN-001") & (data["Windows"]["Status"] == "Open")).sum()), "status": data["Followups"].iloc[0]["Status"]}
        data, tasks, wid = fixture(inactive=True)
        r = app.complete_hardware_task(data, tasks["Trap not ready"], notes="Done.", back_in_service=END + timedelta(hours=1))
        out["s3_inactive"] = {"result": r, "open_windows": int(((data["Windows"]["Trap ID"] == "R1-MAN-001") & (data["Windows"]["Status"] == "Open")).sum()), "status": data["Followups"].iloc[0]["Status"]}
        # S4: refused times write nothing
        data, tasks, wid = fixture(); before = snapshot(data); saves.clear(); errors = {}
        for name, when in (("before", END - timedelta(minutes=1)), ("future", NOW + timedelta(minutes=5)), ("none", None)):
            try:
                app.complete_hardware_task(data, tasks["Trap not ready"], notes="x", back_in_service=when); errors[name] = "no error"
            except ValueError as e:
                errors[name] = str(e)
        out["s4"] = {"errors": errors, "unchanged": same(before, data), "saves": len(saves), "floor": app.task_when(END)}
        # S5: a failure part-way writes nothing
        data, tasks, wid = fixture(); before = snapshot(data); saves.clear()
        real = app.start_window
        def boom(*a, **k): raise RuntimeError("forced failure after the task was staged")
        app.start_window = boom
        try:
            app.complete_hardware_task(data, tasks["Trap not ready"], notes="x", back_in_service=END + timedelta(hours=1)); raised = False
        except RuntimeError:
            raised = True
        app.start_window = real
        out["s5"] = {"raised": raised, "unchanged": same(before, data), "saves": len(saves)}
        # S6: keep open: notes accumulate, status stays Open, the trap stays awaiting service (not a defect)
        data, tasks, wid = fixture(extra_task=True); before = snapshot(data); saves.clear()
        app.keep_hardware_task_open(data, tasks["Trap not ready"], note="Still raining; will return Friday.")
        task = data["Followups"].set_index("Follow-up Type").loc["Trap not ready"]
        app.keep_hardware_task_open(data, task.reset_index().iloc[0] if False else data["Followups"][data["Followups"]["Follow-up Type"] == "Trap not ready"].iloc[0], note="Spring ordered.")
        task = data["Followups"].set_index("Follow-up Type").loc["Trap not ready"]
        out["s6"] = {"status": task["Status"], "notes": task["Notes"], "saves": len(saves), "windows_unchanged": before["Windows"].equals(data["Windows"]),
                     "classify": app.classify_windowless_active_traps(data, "MAN")}
        # S7: a Camera issue kept open applies the past-evidence answer
        data, tasks, wid = fixture(extra_task=True)
        app.keep_hardware_task_open(data, tasks["Camera issue"], note="Needs a new mount.", evidence_gap="Not usable")
        out["s7"] = {"evidence": data["Windows"][data["Windows"]["Window ID"] == wid]["Evidence Usable"].tolist(),
                     "status": data["Followups"].set_index("Follow-up Type").loc["Camera issue", "Status"]}
    print(json.dumps(out, default=str))
"""


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> dict:
    data_dir = tmp_path_factory.mktemp("hw") / "d"; data_dir.mkdir()
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir),
               PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "tests")]))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, f"stdout={r.stdout[-1500:]}\nstderr={r.stderr[-3500:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_the_task_that_closes_last_restarts_the_trap_in_one_write(out):
    first, second = out["s1_first"], out["s1_second"]
    assert first["result"]["restarted"] is False and first["result"]["blocker"] == "another_task" and first["status"] == "Complete"
    assert [w[3] for w in first["windows"]] == ["Closed"], "closing the first of two tasks starts nothing"
    assert second["result"]["restarted"] is True and second["result"]["blocker"] == ""
    assert second["saves"] == 2, "one save per task save: the restart is inside the second, not a separate write"
    assert [w[3] for w in second["windows"]] == ["Closed", "Open"]
    assert second["windows"][1][4] != "", "the new window is stamped with the site's open trial"
    assert second["completed"] == ["Complete", "Complete"]
    assert second["audit"] and second["audit"][0][2] == "Back in service after Trap not ready"
    assert second["when"] == ["2026-10-05 10:00:00"], "it starts at 'Back in service from'"


def test_trap_not_ready_restarts_and_never_writes_the_windows_evidence(out):
    s = out["s2"]
    assert s["result"]["restarted"] and s["saves"] == 1
    assert s["evidence_after"] == s["evidence_before"], "Windows.Evidence Usable is untouched"
    assert s["trial_ids"][0] != "" and s["audit"] == "Back in service after Trap not ready"


@pytest.mark.parametrize("name, blocker", [("s3_has_window", "has_window"), ("s3_inactive", "not_active")])
def test_the_restart_is_refused_but_the_task_still_closes(out, name, blocker):
    s = out[name]
    assert s["result"]["restarted"] is False and s["result"]["blocker"] == blocker and s["status"] == "Complete"
    assert s["open_windows"] == (1 if blocker == "has_window" else 0), "no second window, and none for an inactive trap"


def test_a_time_before_the_closing_check_or_in_the_future_is_refused_and_nothing_is_written(out):
    s = out["s4"]
    assert s["errors"]["before"] == f"Back in service can't be before the check that took it out ({s['floor']})."
    assert s["errors"]["future"] == "Back in service can't be in the future."
    assert s["errors"]["none"] == "Enter when the trap was back in service."
    assert s["unchanged"] and s["saves"] == 0


def test_nothing_is_written_when_the_restart_fails_part_way(out):
    s = out["s5"]
    assert s["raised"] and s["unchanged"] and s["saves"] == 0


def test_keeping_a_task_open_appends_notes_and_leaves_the_trap_awaiting_service(out):
    s = out["s6"]
    assert s["status"] == "Open" and s["saves"] == 2 and s["windows_unchanged"]
    lines = s["notes"].split("\n")
    assert len(lines) == 2 and lines[0].endswith("· Still raining; will return Friday.") and lines[1].endswith("· Spring ordered."), "earlier notes are kept"
    assert s["classify"]["awaiting_service"] == ["R1-MAN-001"] and "R1-MAN-001" not in s["classify"]["defect"]


def test_a_camera_issue_kept_open_still_applies_its_past_evidence_answer(out):
    assert out["s7"] == {"evidence": ["No"], "status": "Open"}
