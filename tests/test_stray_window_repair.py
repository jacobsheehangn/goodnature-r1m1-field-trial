"""One-time repair for a stray open window on an Inactive trap (Phase 0 scan
finding, TRIAL_LIFECYCLE_BRIEF.md). The window is closed with a zero-length
period and excluded from results, with one audit entry, only after the owner
confirms each record; it refuses anything that was actually used."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = "field_trial_data_v8_6_5.xlsx"

_COMMON = """
    import json, datetime, app, pandas as pd
    data = app.create_sample_data()
    site = data["Traps"].iloc[0]["Site ID"]
    traps = data["Traps"][data["Traps"]["Site ID"] == site]["Trap ID"].tolist()
    stray_trap, other_trap, active_trap = traps[0], traps[1], traps[2]
    when = datetime.datetime(2026, 9, 1, 9, 0)
    for t in (stray_trap, other_trap):
        app.deactivate_trap(data, t, when, "reserve", commit=False)

    def add_stray(window_id, trap_id):
        row = {c: "" for c in app.SHEETS["Windows"]}
        t = data["Traps"][data["Traps"]["Trap ID"] == trap_id].iloc[0]
        row.update({"Window ID": window_id, "Trap ID": trap_id, "Product": t["Product"], "Build Version": t["Build Version"],
                    "Site ID": t["Site ID"], "Camera Assigned": "Yes", "Status": "Open", "Start Time": "2026-09-30 16:35:00",
                    "Review Status": "Not required"})
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([row])], ignore_index=True)
    add_stray("STRAY-1", stray_trap)
    app.save_data(data)
"""


def _run(script: str) -> dict:
    env = os.environ.copy()
    env.update(
        {"R1M1_ENVIRONMENT": "local", "R1M1_ALLOW_NO_AUTH": "true", "R1M1_SEED_MODE": "clean", "R1M1_DATA_DIR": tempfile.mkdtemp()}
    )
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_COMMON) + textwrap.dedent(script)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr[-3000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_repair_closes_the_window_excludes_it_and_logs_once() -> None:
    out = _run(
        """
        before_audit = len(data["Audit Log"])
        result = app.close_stray_window(data, "STRAY-1")
        r = app.load_data()
        w = r["Windows"][r["Windows"]["Window ID"] == "STRAY-1"].iloc[0]
        new_audit = r["Audit Log"].iloc[before_audit:]
        # The same filter Trial performance applies to its windows:
        in_results = r["Windows"][(r["Windows"]["Status"] == "Closed") & (r["Windows"]["Excluded"] != "Yes")]["Window ID"].tolist()
        print(json.dumps({
            "result": result, "status": w["Status"], "start": w["Start Time"], "end": w["End Time"], "end_reason": w["End Reason"],
            "review": w["Review Status"], "excluded": w["Excluded"], "exclusion_reason": w["Exclusion Reason"],
            "audit_count": len(new_audit), "audit_type": new_audit.iloc[0]["Record Type"], "audit_id": new_audit.iloc[0]["Record ID"],
            "in_results": "STRAY-1" in in_results,
            "candidates_after": len(app.stray_window_candidates(r)),
            "trap_status": r["Traps"][r["Traps"]["Trap ID"] == stray_trap].iloc[0]["Status"],
        }))
        """
    )
    assert out["status"] == "Closed" and out["end"] == out["start"] == "2026-09-30 16:35:00", "zero-length, kept in the workbook"
    assert out["end_reason"] == "Stray window closed (trap Inactive)" and out["review"] == "Not required"
    assert out["excluded"] == "Yes" and out["exclusion_reason"], "excluded so it never counts in results"
    assert out["in_results"] is False
    assert out["audit_count"] == 1 and out["audit_type"] == "Window" and out["audit_id"] == "STRAY-1"
    assert out["candidates_after"] == 0 and out["trap_status"] == "Inactive"


def test_activating_the_repaired_trap_opens_exactly_one_window() -> None:
    out = _run(
        """
        app.close_stray_window(data, "STRAY-1")
        r = app.load_data()
        trap_row = r["Traps"][r["Traps"]["Trap ID"] == stray_trap].iloc[0]
        app.create_trial(r, site, [app.trial_build_label(trap_row["Product"], trap_row["Build Version"])], datetime.datetime(2026, 10, 6, 8, 0))
        app.activate_trap(r, stray_trap, datetime.datetime(2026, 10, 6, 9, 0), "new trial")
        final = app.load_data()
        w = final["Windows"]
        print(json.dumps({"open": int(((w["Trap ID"] == stray_trap) & (w["Status"] == "Open")).sum())}))
        """
    )
    assert out == {"open": 1}


def test_repair_refuses_anything_that_was_used_or_is_not_a_stray() -> None:
    out = _run(
        """
        def attempt(window_id):
            try:
                app.close_stray_window(data, window_id)
                return "allowed"
            except ValueError as exc:
                return str(exc)
        results = {}
        active_window = app.open_window(data, active_trap)["Window ID"]
        results["active_trap"] = attempt(active_window)
        results["missing"] = attempt("NOPE")
        add_stray("STRAY-2", other_trap)
        crow = {c: "" for c in app.SHEETS["Checks"]}; crow.update({"Check ID": "C1", "Trap ID": other_trap, "Window Closed": "STRAY-2"})
        data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([crow])], ignore_index=True)
        results["used_by_check"] = attempt("STRAY-2")
        data["Checks"] = data["Checks"].iloc[0:0]
        frow = ["F1", "Camera review", site, other_trap, "V", "STRAY-2", "", app.dtstr(), "Normal", "r", "d", "Open", "", ""]
        data["Followups"] = pd.concat([data["Followups"], pd.DataFrame([frow], columns=app.SHEETS["Followups"])], ignore_index=True)
        results["used_by_followup"] = attempt("STRAY-2")
        data["Followups"] = data["Followups"].iloc[0:0]
        prow = {c: "" for c in app.SHEETS["Photos"]}; prow.update({"Photo ID": "P1", "Window ID": "STRAY-2"})
        data["Photos"] = pd.concat([data["Photos"], pd.DataFrame([prow])], ignore_index=True)
        results["used_by_photo"] = attempt("STRAY-2")
        app.close_stray_window(data, "STRAY-1")
        results["already_closed"] = attempt("STRAY-1")
        print(json.dumps(results))
        """
    )
    assert "not Inactive" in out["active_trap"]
    assert "could not be found" in out["missing"]
    assert "1 checks" in out["used_by_check"] and "cannot be closed" in out["used_by_check"]
    assert "1 follow-ups" in out["used_by_followup"]
    assert "1 photos" in out["used_by_photo"]
    assert "not open" in out["already_closed"]


def test_candidates_are_only_open_windows_on_inactive_traps() -> None:
    out = _run(
        """
        listed = app.stray_window_candidates(data)["Window ID"].tolist()
        # an Active trap's open window must never be listed
        active_window = app.open_window(data, active_trap)["Window ID"]
        print(json.dumps({"listed": listed, "active_listed": active_window in listed}))
        """
    )
    assert out == {"listed": ["STRAY-1"], "active_listed": False}


# --- the Data & records screen --------------------------------------------------

STRAY_SEED = """
    import datetime, app, pandas as pd
    data = app.create_sample_data()
    site = data["Traps"].iloc[0]["Site ID"]
    traps = data["Traps"][data["Traps"]["Site ID"] == site]["Trap ID"].tolist()
    for t in traps[:2]:
        app.deactivate_trap(data, t, datetime.datetime(2026, 9, 1, 9, 0), "reserve", commit=False)
    for i, t in enumerate(traps[:2]):
        row = {c: "" for c in app.SHEETS["Windows"]}
        info = data["Traps"][data["Traps"]["Trap ID"] == t].iloc[0]
        row.update({"Window ID": f"STRAY-{i}", "Trap ID": t, "Product": info["Product"], "Build Version": info["Build Version"],
                    "Site ID": site, "Status": "Open", "Start Time": "2026-09-30 16:35:00", "Review Status": "Not required"})
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([row])], ignore_index=True)
    app.save_data(data)
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def stray_app(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env = os.environ.copy()
    env.update({"R1M1_ENVIRONMENT": "local", "R1M1_ALLOW_NO_AUTH": "true", "R1M1_SEED_MODE": "clean", "R1M1_DATA_DIR": str(data_dir)})
    seeded = subprocess.run([sys.executable, "-c", textwrap.dedent(STRAY_SEED)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert seeded.returncode == 0, seeded.stderr[-2000:]
    port = _free_port()
    env2 = env.copy()
    env2["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.address", "127.0.0.1", "--server.port", str(port),
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=ROOT, env=env2, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    ready = False
    try:
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.25)
        assert ready, "app did not become ready"
        yield url, data_dir
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_screen_lists_confirms_and_repairs_one_record_at_a_time(page: Page, stray_app) -> None:
    url, data_dir = stray_app
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Administration", exact=False).click()
    page.get_by_role("link", name="Data & records", exact=True).click()
    expect(page.get_by_text("What you are recording", exact=True)).to_be_visible(timeout=30_000)

    combo = page.get_by_role("combobox", name="Record type", exact=True)
    combo.click()
    page.keyboard.type("Stray window")
    page.get_by_role("option", name="Stray window on an Inactive trap", exact=True).click()
    expect(page.get_by_text("2 Inactive traps with an open window.", exact=True)).to_be_visible(timeout=15_000)

    button = page.get_by_role("button", name="Close this stray window", exact=True)
    expect(button).to_be_disabled()  # nothing happens without the owner's confirmation
    confirm = page.get_by_role("checkbox", name=re.compile("This window is a leftover"))
    confirm.focus()
    page.keyboard.press("Space")
    expect(confirm).to_be_checked(timeout=10_000)
    expect(button).to_be_enabled(timeout=10_000)
    button.click()
    expect(page.get_by_text("Stray window closed.", exact=True)).to_be_visible(timeout=30_000)
    expect(page.get_by_text("1 Inactive trap with an open window.", exact=True)).to_be_visible(timeout=15_000)

    windows = pd.read_excel(data_dir / WORKBOOK, sheet_name="Windows", dtype=str).fillna("")
    strays = windows[windows["Window ID"].str.startswith("STRAY-")]
    closed = strays[strays["Status"] == "Closed"]
    assert len(closed) == 1 and closed.iloc[0]["Excluded"] == "Yes" and closed.iloc[0]["End Time"] == closed.iloc[0]["Start Time"]
    assert (strays["Status"] == "Open").sum() == 1, "only the confirmed record may change"
    audit = pd.read_excel(data_dir / WORKBOOK, sheet_name="Audit Log", dtype=str).fillna("")
    assert (audit["Field"] == "Stray open window").sum() == 1
