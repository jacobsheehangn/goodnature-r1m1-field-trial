"""Regression tests for two 2026-08-13 UX audit findings, both about Corrections
tools silently producing data the app's own rules elsewhere would have rejected:

1. The Necropsy evidence correction form had none of the cross-field consistency
   rules the original Necropsy review task enforces (e.g. "Supports humane kill"
   must pair with Final Humane Kill = Yes) - a correction could save data that
   contradicts itself and flows straight into the humane-kill rate.
2. The Field check correction form only wrote Checks.Finding, never propagating
   to Windows.Finding At Close - since Trial Performance and the Kills sheet are
   entirely Windows-driven, a corrected Finding didn't actually move the numbers.

Runs the real app.py in a subprocess for the pure-function test (no import guard
- see test_derived_sheets.py) and drives the real Corrections UI via Playwright
for the two form-level tests, since both fixes live in inline page-handler code,
not standalone functions.
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


def _select_streamlit_option(page: Page, combobox, filter_text: str, exact: bool = True) -> None:
    """Streamlit's selectbox is a react-aria combobox, not a native <select> -
    a plain click-then-click-option was observed to sometimes not reliably open
    the listbox (state-dependent on the rest of the page), but typing into it
    to filter reliably keeps it open long enough to click the exact option."""
    combobox.click()
    page.keyboard.type(filter_text)
    if exact:
        page.get_by_role("option", name=filter_text, exact=True).click()
    else:
        page.get_by_role("option", name=filter_text, exact=False).first.click()


def _run(tmp_path: Path, script: str) -> dict:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "R1M1_ENVIRONMENT": "local",
            "R1M1_ALLOW_NO_AUTH": "true",
            "R1M1_SEED_MODE": "clean",
            "R1M1_DATA_DIR": str(data_dir),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_necropsy_consistency_errors_covers_all_four_rules(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json, app
        cases = {
            "complete_but_not_assessable": app.necropsy_consistency_errors("Complete", "Not assessable", "Unclear"),
            "supports_but_final_no": app.necropsy_consistency_errors("Complete", "Supports humane kill", "No"),
            "does_not_support_but_final_yes": app.necropsy_consistency_errors("Complete", "Does not support humane kill", "Yes"),
            "not_completed_but_final_yes": app.necropsy_consistency_errors("Not completed", "Pending", "Yes"),
            "unable_to_assess_but_final_no": app.necropsy_consistency_errors("Unable to assess", "Pending", "No"),
            "fully_consistent_support": app.necropsy_consistency_errors("Complete", "Supports humane kill", "Yes"),
            "fully_consistent_non_support": app.necropsy_consistency_errors("Complete", "Does not support humane kill", "No"),
        }
        print(json.dumps({k: len(v) for k, v in cases.items()}))
        """,
    )
    assert out["complete_but_not_assessable"] == 1
    assert out["supports_but_final_no"] == 1
    assert out["does_not_support_but_final_yes"] == 1
    assert out["not_completed_but_final_yes"] == 1
    assert out["unable_to_assess_but_final_no"] == 1
    assert out["fully_consistent_support"] == 0
    assert out["fully_consistent_non_support"] == 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed_and_launch(tmp_path: Path, seed_script: str):
    """Bootstrap the workbook via `seed_script` (must print a JSON line as its
    last line of stdout) before starting Streamlit against the same data dir,
    then wait for the server to become ready. Yields (url, data_dir, seeded)."""
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
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(seed_script)],
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


@pytest.fixture
def necropsy_window_app(tmp_path: Path):
    seed = """
        import json, datetime, app, pandas as pd
        data = app.create_sample_data()
        trap = data["Traps"].iloc[0]
        window_id = "TEST-NEC-WINDOW-1"
        row = {c: "" for c in app.SHEETS["Windows"]}
        row.update({
            "Window ID": window_id, "Trap ID": trap["Trap ID"], "Product": trap["Product"],
            "Build Version": trap["Build Version"], "Site ID": trap["Site ID"], "Status": "Closed",
            "Start Time": "2026-08-01 00:00:00", "End Time": "2026-08-02 00:00:00",
            "Finding At Close": "Dead animal found", "Necropsy Status": "Complete",
            "Necropsy Assessment": "Supports humane kill", "Final Humane Kill": "Yes",
            "Animal Weight Range": "101-150g", "Species": "Rat", "Rat Type": "Norway rat",
        })
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([row])], ignore_index=True)
        app.save_data(data)
        print(json.dumps({"window_id": window_id, "trap_id": trap["Trap ID"], "site_id": trap["Site ID"]}))
    """
    yield from _seed_and_launch(tmp_path, seed)


def test_necropsy_correction_form_blocks_inconsistent_save(
    page: Page, necropsy_window_app
) -> None:
    base_url, data_dir, seeded = necropsy_window_app

    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Administration", exact=False).click()
    page.get_by_role("link", name="Data & records", exact=True).click()
    expect(page.get_by_text("Data & records", exact=True).last).to_be_visible(timeout=30_000)

    _select_streamlit_option(page, page.get_by_role("combobox", name="Record type"), "Necropsy evidence")
    window_picker = page.get_by_role("combobox", name="Select closed test window")
    expect(window_picker).to_be_visible(timeout=15_000)
    _select_streamlit_option(page, window_picker, seeded["window_id"], exact=False)

    # Currently: Necropsy Status=Complete, Assessment=Supports humane kill, Final=Yes
    # (a fully-consistent seeded state). Break consistency by changing Final to "No"
    # while leaving Assessment at "Supports humane kill" - exactly the contradiction
    # necropsy_consistency_errors() exists to catch.
    final_picker = page.get_by_role("combobox", name="Final Humane Kill")
    expect(final_picker).to_be_visible(timeout=15_000)
    _select_streamlit_option(page, final_picker, "No")

    reason_box = page.locator('textarea[aria-label="Correction reason"]')
    reason_box.fill("Regression test: inconsistent necropsy correction")

    page.get_by_role("button", name="Save correction", exact=True).click()
    expect(page.get_by_text("Please correct the necropsy result", exact=False)).to_be_visible(timeout=15_000)
    expect(page.get_by_text("A supportive necropsy must have a final humane-kill result of Yes.", exact=False)).to_be_visible()

    workbook_path = data_dir / "field_trial_data_v8_6_5.xlsx"
    windows = pd.read_excel(workbook_path, sheet_name="Windows", dtype=str)
    saved = windows[windows["Window ID"] == seeded["window_id"]].iloc[0]
    assert saved["Final Humane Kill"] == "Yes", "the blocked, inconsistent save must not have been persisted"


@pytest.fixture
def check_with_window_app(tmp_path: Path):
    seed = """
        import json, datetime, app, pandas as pd
        data = app.create_sample_data()
        trap = data["Traps"].iloc[0]
        window_id = "TEST-CHK-WINDOW-1"
        wrow = {c: "" for c in app.SHEETS["Windows"]}
        wrow.update({
            "Window ID": window_id, "Trap ID": trap["Trap ID"], "Product": trap["Product"],
            "Build Version": trap["Build Version"], "Site ID": trap["Site ID"], "Status": "Closed",
            "Start Time": "2026-08-01 00:00:00", "End Time": "2026-08-02 00:00:00",
            "Finding At Close": "Trap still set, no animal",
        })
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([wrow])], ignore_index=True)
        check_id = "TEST-CHK-1"
        crow = {c: "" for c in app.SHEETS["Checks"]}
        crow.update({
            "Check ID": check_id, "Visit ID": "TEST-VISIT-1", "Trap ID": trap["Trap ID"],
            "Window Closed": window_id, "Check Time": "2026-08-02 00:00:00",
            "Finding": "Trap still set, no animal", "Notes": "",
        })
        data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([crow])], ignore_index=True)
        app.save_data(data)
        print(json.dumps({"window_id": window_id, "check_id": check_id, "trap_id": trap["Trap ID"]}))
    """
    yield from _seed_and_launch(tmp_path, seed)


def test_field_check_correction_propagates_finding_to_its_window(
    page: Page, check_with_window_app
) -> None:
    base_url, data_dir, seeded = check_with_window_app

    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Administration", exact=False).click()
    page.get_by_role("link", name="Data & records", exact=True).click()
    expect(page.get_by_text("Data & records", exact=True).last).to_be_visible(timeout=30_000)

    _select_streamlit_option(page, page.get_by_role("combobox", name="Record type"), "Field check")
    check_picker = page.get_by_role("combobox", name="Select field check")
    expect(check_picker).to_be_visible(timeout=15_000)
    _select_streamlit_option(page, check_picker, seeded["check_id"], exact=False)

    finding_picker = page.get_by_role("combobox", name="Finding", exact=True)
    expect(finding_picker).to_be_visible(timeout=15_000)
    _select_streamlit_option(page, finding_picker, "Dead animal found")

    reason_box = page.locator('textarea[aria-label="Correction reason"]')
    reason_box.fill("Regression test: field-check correction should touch its window")

    page.get_by_role("button", name="Save correction", exact=True).click()
    expect(page.get_by_text("Correction saved.", exact=True)).to_be_visible(timeout=15_000)

    workbook_path = data_dir / "field_trial_data_v8_6_5.xlsx"
    windows = pd.read_excel(workbook_path, sheet_name="Windows", dtype=str)
    saved_window = windows[windows["Window ID"] == seeded["window_id"]].iloc[0]
    assert saved_window["Finding At Close"] == "Dead animal found", (
        "correcting the check's Finding must propagate to the window it closed"
    )
