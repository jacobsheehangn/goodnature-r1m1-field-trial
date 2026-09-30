"""Regression test for a 2026-09-30 field report:

A visit was left "In progress" for weeks after the operator checked only
one trap (which had a kill) and never returned to check the rest. By the
time this was noticed, the site's traps had all been cycled through a full
Deactivate/Activate for a brand new trial, opening fresh windows - so the
remaining traps could never legitimately be checked under that old visit
again (doing so would incorrectly operate on the new trial's windows).

Neither existing "Site check actions" button could close it: "Finish site
check" requires every trap checked (now permanently impossible), and
"Cancel check" only ever applies at zero checks, specifically so it can
never be used to discard real field data - and this visit had one real,
valid check on it (the kill).

Adds a third path: Corrections -> "Incomplete visit", which closes only the
Visit record itself (Status -> "Abandoned"), leaving every Checks/Windows/
Followups row it's linked to completely untouched.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def stale_visit_app(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "R1M1_ENVIRONMENT": "local",
            "R1M1_ALLOW_NO_AUTH": "true",
            "R1M1_SEED_MODE": "clean",
            "R1M1_DATA_DIR": str(data_dir),
        }
    )
    seed = """
        import json, app, pandas as pd
        data = app.create_sample_data()
        trap = data["Traps"][data["Traps"]["Trap ID"] == "M1-MAN-004"].iloc[0]
        trap_id = trap["Trap ID"]
        site_id = trap["Site ID"]

        visit_id = "TEST-STALE-VISIT-1"
        vrow = ["", "", "", "", "", "", ""]
        vrow[0], vrow[1], vrow[2] = visit_id, site_id, "Field operator"
        vrow[3], vrow[4], vrow[5] = "2026-08-10 09:00:00", "", "In progress"
        data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([vrow], columns=app.SHEETS["Visits"])], ignore_index=True)

        window_id = "TEST-STALE-VISIT-W1"
        wrow = {c: "" for c in app.SHEETS["Windows"]}
        wrow.update({
            "Window ID": window_id, "Trap ID": trap_id, "Product": trap["Product"],
            "Build Version": trap["Build Version"], "Site ID": site_id, "Status": "Closed",
            "Start Time": "2026-08-01 00:00:00", "End Time": "2026-08-10 09:05:00",
            "Finding At Close": "Dead animal found", "Review Status": "Open",
        })
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([wrow])], ignore_index=True)

        check_id = "TEST-STALE-VISIT-CHK1"
        crow = {c: "" for c in app.SHEETS["Checks"]}
        crow.update({
            "Check ID": check_id, "Visit ID": visit_id, "Trap ID": trap_id,
            "Window Closed": window_id, "Check Time": "2026-08-10 09:05:00",
            "Finding": "Dead animal found", "Bag ID": "TEST-BAG-1",
        })
        data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([crow])], ignore_index=True)

        app.save_data(data)
        print(json.dumps({"visit_id": visit_id, "site_id": site_id, "trap_id": trap_id, "check_id": check_id}))
    """
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(seed)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    seeded = json.loads(result.stdout.strip().splitlines()[-1])

    port = _free_port()
    env2 = env.copy()
    env2["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.address", "127.0.0.1",
            "--server.port", str(port),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=ROOT, env=env2, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    ready = False
    try:
        import urllib.request

        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Local Streamlit process exited before becoming ready.")
            try:
                with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.25)
        if not ready:
            raise RuntimeError("Local Streamlit app did not become ready within 60 seconds.")
        yield url, data_dir, seeded
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_abandoning_a_stale_visit_closes_it_without_touching_its_real_check(
    page: Page, stale_visit_app
) -> None:
    base_url, data_dir, seeded = stale_visit_app
    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Administration", exact=False).click()
    page.get_by_role("link", name="Data & records", exact=True).click()
    expect(page.get_by_text("Data & records", exact=True).last).to_be_visible(timeout=30_000)

    combobox = page.get_by_role("combobox", name="Record type")
    combobox.click()
    page.keyboard.type("Incomplete visit")
    page.get_by_role("option", name="Incomplete visit", exact=True).click()

    expect(page.get_by_text("Checks recorded: 1", exact=False)).to_be_visible(timeout=15_000)

    reason_box = page.get_by_role("textbox", name="Reason for abandoning this visit", exact=True)
    reason_box.fill("Site traps moved to a new trial before this visit was finished.")

    confirm_checkbox = page.get_by_role("checkbox", name="Close out this visit", exact=False)
    confirm_checkbox.focus()
    page.keyboard.press("Space")
    expect(confirm_checkbox).to_be_checked(timeout=10_000)

    abandon_button = page.get_by_role("button", name="Abandon this visit", exact=True)
    expect(abandon_button).to_be_enabled(timeout=10_000)
    abandon_button.click()
    expect(page.get_by_text("Visit closed.", exact=True)).to_be_visible(timeout=15_000)

    workbook_path = data_dir / "field_trial_data_v8_6_5.xlsx"
    visits = pd.read_excel(workbook_path, sheet_name="Visits", dtype=str)
    saved_visit = visits[visits["Visit ID"] == seeded["visit_id"]].iloc[0]
    assert saved_visit["Status"] == "Abandoned"
    assert saved_visit["End Time"], "abandoning should stamp an End Time"

    checks = pd.read_excel(workbook_path, sheet_name="Checks", dtype=str)
    saved_check = checks[checks["Check ID"] == seeded["check_id"]].iloc[0]
    assert saved_check["Finding"] == "Dead animal found", (
        "the real check recorded under this visit must be left completely untouched"
    )

    audit = pd.read_excel(workbook_path, sheet_name="Audit Log", dtype=str)
    visit_audit = audit[(audit["Record Type"] == "Visit") & (audit["Record ID"] == seeded["visit_id"])]
    assert not visit_audit.empty, "abandoning a visit must be recorded in the audit log"

    # The site should now offer a fresh visit, not resume the abandoned one.
    page.get_by_role("link", name="Trap sites", exact=True).click()
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    expect(page.get_by_role("button", name="Resume checking", exact=False)).to_have_count(0)
