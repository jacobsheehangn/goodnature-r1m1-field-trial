"""Phase 5 (TRIAL_LIFECYCLE_BRIEF.md, A2): a kill with no carcass.

Bare-mode tests of the one-time correction for the existing records that were
saved as a collected carcass when nothing was recovered, and of the lists that
must know the new status values. The check form itself and the Trial
Performance numbers are covered in test_no_carcass_ui.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_COMMON = """
    import json, app, pandas as pd
    data = app.create_sample_data()
    trap = data["Traps"].iloc[0]
    wid, fid, cam_fid, check_id = "TEST-NC-W", "TEST-NC-FU", "TEST-NC-CAM", "TEST-NC-CHK"

    def add_kill(bag="BAG-001", final="Pending", necropsy_status="Not started", open_necropsy=True, photo=False):
        wrow = {c: "" for c in app.SHEETS["Windows"]}
        wrow.update({
            "Window ID": wid, "Trap ID": trap["Trap ID"], "Site ID": trap["Site ID"], "Status": "Closed",
            "Start Time": "2026-08-01 00:00:00", "End Time": "2026-08-02 00:00:00",
            "Finding At Close": "Dead animal found", "Bag ID": bag, "Camera Assigned": "Yes", "Species": "Rat",
            "Final Humane Kill": final, "Necropsy Status": necropsy_status, "Review Status": "Open",
        })
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([wrow])], ignore_index=True)
        crow = {c: "" for c in app.SHEETS["Checks"]}
        crow.update({"Check ID": check_id, "Visit ID": "V", "Trap ID": trap["Trap ID"], "Window Closed": wid,
                     "Check Time": "2026-08-02 00:00:00", "Finding": "Dead animal found", "Bag ID": bag,
                     "Animal Cleared": "Yes", "Animal Bagged": "Yes", "Animal Condition When Found": "Dead and apparently normal"})
        data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([crow])], ignore_index=True)
        rows = [
            [cam_fid, "Camera review", trap["Site ID"], trap["Trap ID"], "V", wid, bag, app.dtstr(), "Normal", "r", "d", "Open", "", ""],
            [fid, "Necropsy review", trap["Site ID"], trap["Trap ID"], "V", wid, bag, app.dtstr(), "Normal", "r", "d", "Open" if open_necropsy else "Complete", "", ""],
        ]
        data["Followups"] = pd.concat([data["Followups"], pd.DataFrame(rows, columns=app.SHEETS["Followups"])], ignore_index=True)
        if photo:
            prow = {c: "" for c in app.SHEETS["Photos"]}
            prow.update({"Photo ID": "P1", "Check ID": check_id, "Window ID": wid, "Bag ID": bag})
            data["Photos"] = pd.concat([data["Photos"], pd.DataFrame([prow])], ignore_index=True)
"""


def _run(script: str) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "R1M1_ENVIRONMENT": "local",
            "R1M1_ALLOW_NO_AUTH": "true",
            "R1M1_SEED_MODE": "clean",
            "R1M1_DATA_DIR": tempfile.mkdtemp(),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_COMMON) + textwrap.dedent(script)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr[-3000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_correction_sets_the_no_carcass_values_clears_the_bag_and_logs_once() -> None:
    out = _run(
        """
        add_kill()
        app.save_data(data)
        before_audit = len(data["Audit Log"])
        result = app.correct_kill_to_no_carcass(data, wid)
        reloaded = app.load_data()
        w = reloaded["Windows"][reloaded["Windows"]["Window ID"] == wid].iloc[0]
        c = reloaded["Checks"][reloaded["Checks"]["Check ID"] == check_id].iloc[0]
        fus = reloaded["Followups"][reloaded["Followups"]["Window ID"] == wid].set_index("Follow-up Type")
        new_audit = reloaded["Audit Log"].iloc[before_audit:]
        print(json.dumps({
            "result": result,
            "fhk": w["Final Humane Kill"], "necropsy_status": w["Necropsy Status"], "window_bag": w["Bag ID"],
            "finding": w["Finding At Close"], "review_status": w["Review Status"],
            "check_bag": c["Bag ID"], "cleared": c["Animal Cleared"], "bagged": c["Animal Bagged"],
            "necropsy_task": fus.loc["Necropsy review", "Status"], "necropsy_task_bag": fus.loc["Necropsy review", "Bag ID"],
            "camera_task": fus.loc["Camera review", "Status"], "camera_task_bag": fus.loc["Camera review", "Bag ID"],
            "audit_count": len(new_audit), "audit_type": new_audit.iloc[0]["Record Type"], "audit_new": new_audit.iloc[0]["New Value"],
            "kills_row_bag": reloaded["Kills"][reloaded["Kills"]["Window ID"] == wid].iloc[0]["Bag ID"],
            "candidates_after": len(app.no_carcass_correction_candidates(reloaded)),
        }))
        """
    )
    assert out["fhk"] == "Not assessed — no carcass"
    assert out["necropsy_status"] == "Not applicable — no carcass"
    assert out["window_bag"] == "" and out["check_bag"] == "", "the phantom Bag ID must be cleared"
    assert out["cleared"] == "No" and out["bagged"] == "No"
    assert out["finding"] == "Dead animal found", "it must stay a kill"
    assert out["necropsy_task"] == "Resolved — no carcass collected", "a distinct status, never 'Complete'"
    assert out["camera_task"] == "Open", "the camera review is untouched"
    assert out["necropsy_task_bag"] == "" and out["camera_task_bag"] == ""
    assert out["review_status"] == "Open", "the open camera review still keeps the window's review open"
    assert out["audit_count"] == 1 and out["audit_type"] == "Kill record" and out["audit_new"] == "No"
    assert out["kills_row_bag"] == "", "the derived Kills sheet shows no bag"
    assert out["candidates_after"] == 0


def test_correction_refuses_anything_that_contradicts_no_carcass() -> None:
    out = _run(
        """
        def attempt():
            try:
                app.correct_kill_to_no_carcass(data, wid)
                return "allowed"
            except ValueError as exc:
                return str(exc)
        results = {}
        add_kill(final="Yes")                               # already has a final result
        results["final_result_set"] = attempt()
        data = app.create_sample_data(); trap = data["Traps"].iloc[0]
        add_kill(open_necropsy=False)                       # necropsy task already done
        results["no_open_task"] = attempt()
        data = app.create_sample_data(); trap = data["Traps"].iloc[0]
        add_kill(photo=True)                                # photos exist, so a carcass was collected
        results["photos_attached"] = attempt()
        data = app.create_sample_data(); trap = data["Traps"].iloc[0]
        results["missing_window"] = attempt()
        print(json.dumps(results))
        """
    )
    assert "already has a final result" in out["final_result_set"]
    assert "no open necropsy review" in out["no_open_task"]
    assert "Photos are attached" in out["photos_attached"]
    assert "could not be found" in out["missing_window"]


def test_candidates_list_only_pending_dead_animal_kills_with_an_open_necropsy_review() -> None:
    out = _run(
        """
        add_kill()
        ids = app.no_carcass_correction_candidates(data)["Window ID"].tolist()
        data = app.create_sample_data(); trap = data["Traps"].iloc[0]
        add_kill(final="Yes")
        none_when_assessed = app.no_carcass_correction_candidates(data)["Window ID"].tolist()
        print(json.dumps({"listed": ids, "assessed": none_when_assessed}))
        """
    )
    assert out == {"listed": ["TEST-NC-W"], "assessed": []}


def test_a_no_carcass_kill_is_not_warranted_for_a_necropsy_and_is_not_awaiting() -> None:
    out = _run(
        """
        add_kill(final=app.NOT_ASSESSED_NO_CARCASS, necropsy_status=app.NECROPSY_NOT_APPLICABLE_NO_CARCASS, open_necropsy=False)
        data["Followups"] = data["Followups"][data["Followups"]["Follow-up Type"] != "Necropsy review"]
        data["Followups"] = data["Followups"][data["Followups"]["Follow-up Type"] != "Camera review"]
        w = data["Windows"][data["Windows"]["Window ID"] == wid].iloc[0]
        app.refresh_review_status(data, wid)
        status = data["Windows"][data["Windows"]["Window ID"] == wid].iloc[0]["Review Status"]
        s = pd.Series(["Yes", "No", "Pending", "Not assessable", "Unclear", app.NOT_ASSESSED_NO_CARCASS, app.NOT_ASSESSED_TRIAL_ENDED, ""])
        print(json.dumps({
            "warranted": bool(app.followup_genuinely_warranted(w)),
            "review_status_with_camera_but_no_task": status,
            "not_assessed_mask": app.not_assessed_mask(s).tolist(),
        }))
        """
    )
    assert out["warranted"] is True, "this window has a camera, so a camera review is still warranted (its Final Humane Kill is not 'Pending')"
    assert out["review_status_with_camera_but_no_task"] == "Needs recreation"
    assert out["not_assessed_mask"] == [False, False, False, False, False, True, True, False]
