"""Regression test for the bulk-activate stale-preview bug found in the
2026-08-13 UX audit.

Clicking "Preview activation" used to freeze the selected trap list and shared
date/time into session state, but the selection checkboxes and date/time inputs
above stayed live and fully interactive underneath the shown preview - so
changing the selection after previewing could silently commit something
different from what the preview displayed. The fix locks those inputs once a
preview is pending, so Cancel is the only way to change the selection.

Drives the real bulk-activate UI in a browser (not the underlying Python
functions, which already had full pytest coverage in test_trap_activation.py -
this specifically covers the widget-locking behavior that coverage couldn't
reach) and confirms: (1) the second trap's Select checkbox becomes disabled
once a preview is pending, and (2) only the originally-previewed trap actually
gets activated, matching what the preview showed.
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


def _seed_two_inactive_traps(data_dir: Path) -> dict:
    """Bootstrap the workbook with 2 Inactive traps *before* Streamlit starts,
    using the same deactivate_trap() the app itself calls (not hand-rolled
    data), so this only tests the bulk-activate UI, not trap-deactivation
    logic - that's already covered separately in test_trap_activation.py."""
    env = os.environ.copy()
    env.update(
        {
            "R1M1_ENVIRONMENT": "local",
            "R1M1_ALLOW_NO_AUTH": "true",
            "R1M1_SEED_MODE": "clean",
            "R1M1_DATA_DIR": str(data_dir),
        }
    )
    script = """
        import json, datetime, app
        data = app.create_sample_data()
        trap_ids = data["Traps"]["Trap ID"].tolist()[:2]
        for trap_id in trap_ids:
            app.deactivate_trap(data, trap_id, datetime.datetime(2026, 8, 12, 9, 0), "Test setup", commit=False)
        app.save_data(data)
        print(json.dumps({"trap_ids": trap_ids}))
    """
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture
def bulk_activate_app(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    seeded = _seed_two_inactive_traps(data_dir)

    port = _free_port()
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
        yield url, data_dir, seeded["trap_ids"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_preview_locks_selection_and_commits_exactly_what_it_showed(
    page: Page, bulk_activate_app
) -> None:
    base_url, data_dir, trap_ids = bulk_activate_app
    trap_a, trap_b = trap_ids

    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Administration", exact=False).click()
    page.get_by_role("link", name="Trial setup", exact=True).click()
    expect(page.get_by_text("Trial setup", exact=True).last).to_be_visible(timeout=30_000)

    expander = page.get_by_text("Bulk activate traps (2 inactive)", exact=True)
    expect(expander).to_be_visible(timeout=15_000)
    expander.click()

    reason_box = page.get_by_placeholder("e.g. New traps deployed for tomorrow's field pass.")
    expect(reason_box).to_be_visible(timeout=10_000)
    reason_box.fill("Regression test: bulk-activate preview lock")

    # The bulk-activate list is sorted by Site ID then Trap ID (same order as
    # the seeded trap_ids), so the first "Select" checkbox is trap_a's and the
    # second is trap_b's - select only trap A. This checkbox is a react-aria
    # Pressable component (visually-hidden <input>, custom press handling on
    # its parent <label>) that doesn't reliably respond to a plain click, even
    # in real Playwright/Chromium - genuine keyboard focus + Space does.
    select_checkboxes = page.get_by_role("checkbox", name="Select")
    expect(select_checkboxes).to_have_count(2, timeout=10_000)
    select_checkboxes.nth(0).focus()
    page.keyboard.press("Space")
    expect(select_checkboxes.nth(0)).to_be_checked(timeout=10_000)

    page.get_by_role("button", name="Preview activation", exact=True).click()
    expect(page.get_by_text("Confirm bulk activation", exact=True)).to_be_visible(timeout=15_000)

    # Trap B's Select checkbox must now be disabled - proving the selection is
    # locked once a preview is pending, not silently changeable underneath it.
    expect(select_checkboxes.nth(1)).to_be_disabled(timeout=10_000)

    page.get_by_role("button", name="Confirm bulk activate", exact=True).click()
    expect(page.get_by_text("Bulk activation applied.", exact=True)).to_be_visible(timeout=15_000)

    workbook_path = data_dir / "field_trial_data_v8_6_5.xlsx"
    traps = pd.read_excel(workbook_path, sheet_name="Traps", dtype=str)
    status_by_id = dict(zip(traps["Trap ID"], traps["Status"]))
    assert status_by_id[trap_a] == "Active", "the previewed/selected trap should be Active"
    assert status_by_id[trap_b] == "Inactive", "the never-selected trap must stay Inactive, not get swept in"
