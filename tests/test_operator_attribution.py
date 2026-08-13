"""Regression test for the hardcoded-operator-attribution gap found in the
2026-08-13 UX audit.

field_operator defaulted to a hardcoded name, and the only <text_input> that could
change it lived in a dead, unreachable page handler - so every visit recorded
through the real field workflow was silently attributed to whatever the default
happened to be, with no way to fix it in the live app. The fix adds a real Operator
field to the Administration popover (reachable from every page, same as Sign out).
This drives it through the real UI and confirms the saved Visit row actually
reflects the operator name that was set, not just that the widget renders.
"""
from __future__ import annotations

import os
import re
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
def local_app_with_data_dir(tmp_path: Path):
    """Same launch as the shared `local_app` fixture, but also yields the data dir
    so the test can inspect the saved workbook directly."""
    port = _free_port()
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

    process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.address", "127.0.0.1",
            "--server.port", str(port),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
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


def test_setting_operator_in_admin_menu_attributes_the_recorded_visit(
    page: Page, local_app_with_data_dir
) -> None:
    base_url, data_dir = local_app_with_data_dir
    operator_name = "Priya Test-Operator"

    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Administration", exact=False).click()
    operator_input = page.get_by_role("textbox", name="Operator", exact=True)
    expect(operator_input).to_be_visible(timeout=10_000)
    operator_input.fill(operator_name)
    operator_input.press("Enter")

    # Close the popover, then start a visit at the first site.
    page.keyboard.press("Escape")
    page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)

    workbook_path = data_dir / "field_trial_data_v8_6_5.xlsx"
    visits = pd.DataFrame()
    for _ in range(60):
        if workbook_path.exists():
            visits = pd.read_excel(workbook_path, sheet_name="Visits", dtype=str)
            if not visits.empty:
                break
        page.wait_for_timeout(500)
    else:
        pytest.fail("Visits sheet never appeared after starting a visit.")
    assert not visits.empty, "expected at least one Visit row after starting checking"
    assert (visits["Operator"] == operator_name).any(), (
        f"expected a Visit row attributed to {operator_name!r}, got {visits['Operator'].tolist()!r}"
    )
