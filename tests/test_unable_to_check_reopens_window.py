"""Regression test for a 2026-08-24 field report:

A trap ended up Active with no open test window, dead-ending on "This trap
has no active test window" with no working in-app fix - "Start window and
continue" always failed for a trap with prior history, forcing a manual
Deactivate-then-Activate round trip in Administration just to get back to a
normal state.

Root cause (confirmed from the field): the operator couldn't reach the trap
on a visit and picked "Unable to check". That finding is (correctly) not
assessable - but the check-save handler's `will_start` flag lumped it in
with "Trap missing", so the check closed the trap's window and started no
new one. Unlike "Trap missing" (the trap is physically gone, so there really
is nothing to monitor until it's found), "Unable to check" means the trap's
physical state is unchanged from the last visit - it should keep monitoring
uninterrupted, not get stranded.

The fix: "Unable to check" now reopens a window immediately, same as a
normal completed check. "Trap missing" is deliberately left as before. A
second, related bug is fixed alongside it: the "Trap Ready After Check"
column (surfaced in the trap's Full history as "Trap ready: ...") was
written as a flat "Yes"/"No" even when the question was never asked for a
non-assessable finding, showing a misleading "Trap ready: No" that looked
like an operator answer instead of "the trap was never assessed".
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
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
def local_app_url(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "R1M1_ENVIRONMENT": "local",
            "R1M1_ALLOW_NO_AUTH": "true",
            "R1M1_SEED_MODE": "clean",
            "R1M1_DATA_DIR": str(data_dir),
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        }
    )
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.address", "127.0.0.1",
            "--server.port", str(port),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
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
        yield url, data_dir
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_unable_to_check_reopens_a_window_instead_of_stranding_the_trap(
    page: Page, local_app_url
) -> None:
    base_url, data_dir = local_app_url
    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Start checking", exact=False).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)

    check_button = page.get_by_role("button", name="Check", exact=True).first
    check_button.click()
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)
    query = dict(pair.split("=") for pair in page.url.split("?", 1)[1].split("&") if "=" in pair)
    trap_id = query.get("wf_trap", "")

    # The warning shown for this finding should now describe automatic
    # recovery, not a dead-ending closure - regression coverage for the
    # message update alongside the behavioural fix.
    page.get_by_text("Unable to check", exact=True).click()
    expect(page.get_by_role("radio", name="Unable to check", exact=True)).to_be_checked(timeout=10_000)
    expect(page.get_by_text("start a new monitoring window automatically", exact=False)).to_be_visible(timeout=10_000)

    save_button = page.get_by_role("button", name="Save check", exact=True)
    expect(save_button).to_be_enabled(timeout=10_000)
    save_button.click()
    expect(page.get_by_text("saved", exact=False).first).to_be_visible(timeout=30_000)

    workbook_path = data_dir / "field_trial_data_v8_6_5.xlsx"
    windows = pd.read_excel(workbook_path, sheet_name="Windows", dtype=str)
    trap_windows = windows[windows["Trap ID"] == trap_id]
    open_windows = trap_windows[trap_windows["Status"] == "Open"]
    assert len(open_windows) == 1, (
        "an 'Unable to check' save must leave exactly one open window for the trap, "
        f"not strand it - found {len(open_windows)}"
    )

    checks = pd.read_excel(workbook_path, sheet_name="Checks", dtype=str)
    saved_check = checks[checks["Trap ID"] == trap_id].iloc[-1]
    assert saved_check["Trap Ready After Check"] == "Not assessed", (
        "the trap-service question was never asked for a non-assessable finding - "
        "the column must say so, not silently claim 'No' as if the operator answered it"
    )
    assert saved_check["New Window"] == open_windows.iloc[0]["Window ID"], (
        "the check's own 'New Window' record should point at the window that got reopened"
    )
