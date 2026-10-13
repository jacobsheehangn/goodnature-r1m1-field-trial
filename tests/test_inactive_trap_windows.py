"""Phase 0 (TRIAL_LIFECYCLE_BRIEF.md): moving or re-building an Inactive trap
must never open a window on it (activate_trap() assumes an Inactive trap has
none, so a stray window would become a second open window on activation), and
move_trap() gets a `commit` option like its siblings. Also covers the
read-only stray-window scan script."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_COMMON = """
    import json, datetime, app, pandas as pd
    data = app.create_sample_data()
    site_a = data["Traps"].iloc[0]["Site ID"]
    site_b = data["Traps"][data["Traps"]["Site ID"] != site_a].iloc[0]["Site ID"]
    when = datetime.datetime(2026, 9, 1, 9, 0)

    def open_count(d, trap_id):
        return int(((d["Windows"]["Trap ID"] == trap_id) & (d["Windows"]["Status"] == "Open")).sum())

    def window_count(d, trap_id):
        return int((d["Windows"]["Trap ID"] == trap_id).sum())

    def trap(d, trap_id):
        return d["Traps"][d["Traps"]["Trap ID"] == trap_id].iloc[0]

    active_id = data["Traps"][data["Traps"]["Site ID"] == site_a].iloc[0]["Trap ID"]
    inactive_id = data["Traps"][data["Traps"]["Site ID"] == site_a].iloc[1]["Trap ID"]
    app.deactivate_trap(data, inactive_id, when, "stage", commit=False)
    app.save_data(data)
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


def test_moving_an_inactive_trap_updates_it_without_opening_a_window() -> None:
    out = _run(
        """
        windows_before = window_count(data, inactive_id)
        audit_before = len(data["Audit Log"])
        result = app.move_trap(data, inactive_id, site_b, when, "stage elsewhere", 7, "New spot", "")
        reloaded = app.load_data()
        t = trap(reloaded, inactive_id)
        print(json.dumps({
            "returned": result, "site": t["Site ID"], "order": t["Route Order"], "location": t["Location"], "status": t["Status"],
            "open": open_count(reloaded, inactive_id), "windows_added": window_count(reloaded, inactive_id) - windows_before,
            "audit_added": len(reloaded["Audit Log"]) - audit_before,
        }))
        """
    )
    assert out["site"] and out["order"] == "7" and out["location"] == "New spot"
    assert out["status"] == "Inactive"
    assert out["open"] == 0 and out["windows_added"] == 0, "an Inactive trap must get no window"
    assert out["returned"] == ""
    assert out["audit_added"] == 3, "the site, route order and location changes are still audited"


def test_rebuilding_an_inactive_trap_updates_it_without_opening_a_window() -> None:
    out = _run(
        """
        windows_before = window_count(data, inactive_id)
        audit_before = len(data["Audit Log"])
        result = app.change_trap_build(data, inactive_id, "R1", "R1 Build 4.2", when, "stage a build")
        reloaded = app.load_data()
        t = trap(reloaded, inactive_id)
        new_audit = reloaded["Audit Log"].iloc[audit_before:]
        print(json.dumps({
            "returned": result, "build": t["Build Version"], "status": t["Status"], "open": open_count(reloaded, inactive_id),
            "windows_added": window_count(reloaded, inactive_id) - windows_before,
            "audit_fields": new_audit["Field"].tolist(),
        }))
        """
    )
    assert out["build"] == "R1 Build 4.2" and out["status"] == "Inactive"
    assert out["open"] == 0 and out["windows_added"] == 0
    assert out["returned"] == ""
    assert out["audit_fields"] == ["Build Version"]


def test_rebuild_then_activate_leaves_exactly_one_open_window() -> None:
    out = _run(
        """
        app.change_trap_build(data, inactive_id, "R1", "R1 Build 4.2", when, "stage a build", commit=False)
        app.move_trap(data, inactive_id, site_b, when, "stage elsewhere", 3, "Spot", "", commit=False)
        # Activation needs the destination site to have an Open trial declaring the new build (T2).
        app.create_trial(data, site_b, ["R1 · R1 Build 4.2"], when)
        app.activate_trap(data, inactive_id, when + datetime.timedelta(hours=1), "start trial", commit=False)
        app.save_data(data)
        reloaded = app.load_data()
        print(json.dumps({"open": open_count(reloaded, inactive_id), "status": trap(reloaded, inactive_id)["Status"],
                          "site": trap(reloaded, inactive_id)["Site ID"] == site_b}))
        """
    )
    assert out == {"open": 1, "status": "Active", "site": True}


def test_active_trap_at_an_untracked_site_can_change_build_but_not_move() -> None:
    """The sample data has no Trials rows, so this site is untracked: a build
    change on an Active trap keeps closing the window and opening a new one, as
    before. Moving an Active trap is now refused (T6) and must change nothing."""
    out = _run(
        """
        windows_before = window_count(data, active_id)
        old_window = app.open_window(data, active_id)["Window ID"]
        new_window = app.change_trap_build(data, active_id, "R1", "R1 Build 4.2", when, "change build")
        after_build = app.load_data()
        move_error = ""
        try:
            app.move_trap(after_build, active_id, site_b, when + datetime.timedelta(hours=1), "move", 4, "Elsewhere", "")
        except ValueError as exc:
            move_error = str(exc)
        final = app.load_data()
        w = final["Windows"]
        print(json.dumps({
            "build_window_new": bool(new_window) and new_window != old_window,
            "open": open_count(final, active_id), "windows_added": window_count(final, active_id) - windows_before,
            "old_closed_by": w[w["Window ID"] == old_window].iloc[0]["End Reason"],
            "open_window_is_the_new_one": app.open_window(final, active_id)["Window ID"] == new_window,
            "site_unchanged": trap(final, active_id)["Site ID"] == site_a,
            "move_error": move_error,
        }))
        """
    )
    assert out["build_window_new"] and out["open"] == 1 and out["windows_added"] == 1
    assert out["old_closed_by"] == "Build changed"
    assert out["move_error"].startswith("Deactivate this trap before moving it.")
    assert out["site_unchanged"] and out["open_window_is_the_new_one"], "a refused move must leave the trap and its window alone"


def test_move_trap_commit_false_leaves_the_save_to_the_caller() -> None:
    out = _run(
        """
        app.move_trap(data, inactive_id, site_b, when, "stage", 5, "Spot", "", commit=False)
        on_disk = app.load_data()
        not_saved = trap(on_disk, inactive_id)["Site ID"] == site_a
        app.save_data(data)
        saved = trap(app.load_data(), inactive_id)["Site ID"] == site_b
        print(json.dumps({"not_saved_yet": bool(not_saved), "saved_after_caller_commit": bool(saved)}))
        """
    )
    assert out == {"not_saved_yet": True, "saved_after_caller_commit": True}


def test_a_stray_window_on_an_inactive_trap_is_left_alone_not_made_worse() -> None:
    out = _run(
        """
        # Simulate existing damage: an Inactive trap that already has an open window.
        row = {c: "" for c in app.SHEETS["Windows"]}
        row.update({"Window ID": "STRAY-1", "Trap ID": inactive_id, "Site ID": site_a, "Status": "Open", "Start Time": "2026-09-02 00:00:00"})
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([row])], ignore_index=True)
        app.save_data(data)
        app.change_trap_build(data, inactive_id, "R1", "R1 Build 4.2", when, "stage")
        app.move_trap(data, inactive_id, site_b, when, "stage", 2, "Spot", "")
        reloaded = app.load_data()
        w = reloaded["Windows"]
        stray = w[w["Window ID"] == "STRAY-1"].iloc[0]
        print(json.dumps({"open": open_count(reloaded, inactive_id), "stray_status": stray["Status"], "stray_end": stray["End Time"]}))
        """
    )
    assert out == {"open": 1, "stray_status": "Open", "stray_end": ""}, "repairs are a human decision, never a side effect"


# --- the read-only scan -------------------------------------------------------

def _workbook(tmp: Path) -> Path:
    traps = pd.DataFrame(
        [
            ["T-OK", "R1", "R1 Build 4.3", "S1", "Active"],
            ["T-SERVICE", "R1", "R1 Build 4.3", "S1", "Active"],
            ["T-MISSING", "R1", "R1 Build 4.3", "S1", "Active"],
            ["T-DEFECT", "R1", "R1 Build 4.3", "S1", "Active"],
            ["T-DOUBLE", "R1", "R1 Build 4.3", "S1", "Active"],
            ["T-STRAY", "R1", "R1 Build 4.3", "S1", "Inactive"],
            ["T-CLEAN", "R1", "R1 Build 4.3", "S1", "Inactive"],
        ],
        columns=["Trap ID", "Product", "Build Version", "Site ID", "Status"],
    )

    def w(wid, trap_id, status, end="", finding=""):
        return {"Window ID": wid, "Trap ID": trap_id, "Status": status, "Start Time": "2026-09-01 08:00:00", "End Time": end, "Finding At Close": finding}

    windows = pd.DataFrame(
        [
            w("W1", "T-OK", "Open"),
            w("W2", "T-SERVICE", "Closed", "2026-09-02 08:00:00", "Trap still set, no animal"),
            w("W3", "T-MISSING", "Closed", "2026-09-02 08:00:00", "Trap missing"),
            w("W4", "T-DEFECT", "Closed", "2026-09-02 08:00:00", "Trap still set, no animal"),
            w("W5", "T-DOUBLE", "Open"),
            w("W6", "T-DOUBLE", "Open"),
            w("W7", "T-STRAY", "Open"),
        ]
    )
    followups = pd.DataFrame(
        [
            {"Follow-up ID": "F1", "Follow-up Type": "Trap not ready", "Trap ID": "T-SERVICE", "Status": "Open"},
            {"Follow-up ID": "F2", "Follow-up Type": "Camera issue", "Trap ID": "T-DEFECT", "Status": "Complete"},
        ]
    )
    path = tmp / "scan_fixture.xlsx"
    with pd.ExcelWriter(path) as writer:
        traps.to_excel(writer, sheet_name="Traps", index=False)
        windows.to_excel(writer, sheet_name="Windows", index=False)
        followups.to_excel(writer, sheet_name="Followups", index=False)
    return path


def test_scan_classifies_each_state_and_never_touches_the_workbook() -> None:
    import scan_trap_windows as scan_module

    tmp = Path(tempfile.mkdtemp())
    path = _workbook(tmp)
    before = (path.stat().st_mtime_ns, path.read_bytes())
    result = scan_module.scan(path)
    report = scan_module.format_report(result)

    assert [r["Trap ID"] for r in result["A_inactive_with_open_window"]] == ["T-STRAY"]
    assert [r["Trap ID"] for r in result["B_active_with_multiple_open_windows"]] == ["T-DOUBLE"]
    c = result["C_active_without_open_window"]
    assert [r["Trap ID"] for r in c["awaiting_service (legitimate)"]] == ["T-SERVICE"]
    assert [r["Trap ID"] for r in c["trap_missing (legitimate)"]] == ["T-MISSING"]
    assert [r["Trap ID"] for r in c["DEFECT (needs a decision)"]] == ["T-DEFECT"], (
        "a resolved camera-issue follow-up must not excuse a windowless Active trap"
    )
    assert "A. Inactive traps with an open window: 1" in report and "DEFECT (needs a decision): 1" in report
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before, "the scan must be strictly read-only"
