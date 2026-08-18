"""Regression test for a field-reported bug in the Window start corrections
tool (Data & records page): tapping "Apply this trap" or "Confirm bulk apply"
right after entering a reason gave no visible feedback that anything was
happening - the same "tap button not clear anything is happening" complaint
that test_button_loading_feedback.py already covers for "Check" and
"Save check".

Root cause is the same one described there: both buttons did their slow work
(the correction + workbook write) in the SAME script pass that first detected
the click, so a disabled/relabelled button state was never actually painted
before the browser moved on - Streamlit only repaints a widget on a full
script rerun, and by the time one happened here, the work was already done.

The fix is the same two-phase pattern already used for "Check"/"Save check":
acknowledge the tap and rerun immediately (cheap, no I/O) so the *next*
rerun genuinely shows the button disabled/relabelled "Applying…" before the
correction is written. This is directly testable: before the fix there was
no intermediate disabled state to observe at all; after the fix, there is a
real, distinct render pass that shows it.

Uses `create_sample_data()` directly (no bespoke seeding needed): its R1
traps are deployed 14 days ago but their sample window starts ~60 hours ago,
which always lands on a different calendar day - exactly the "suspect
earliest window" signature `suspect_earliest_window_candidates()` flags, so
every R1 trap it creates already qualifies as an eligible correction
candidate.
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

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def window_start_corrections_app(tmp_path: Path):
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
    seed_script = """
        import json, app
        data = app.create_sample_data()
        app.save_data(data)
        r1 = app.suspect_earliest_window_candidates(data, "R1")
        print(json.dumps({"count": len(r1)}))
    """
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(seed_script)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    seeded = json.loads(result.stdout.strip().splitlines()[-1])
    assert seeded["count"] > 1, "need at least two suspect R1 candidates for the bulk-apply test"

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
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _open_window_start_corrections(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Administration", exact=True).click()
    page.get_by_role("link", name="Data & records", exact=True).click()
    expect(page.get_by_text("Data & records", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_text("Window start corrections", exact=True).click()
    expect(page.get_by_text("Reason for these corrections", exact=False)).to_be_visible(timeout=15_000)


def test_apply_this_trap_shows_a_disabled_applying_state_before_completing(
    page: Page, window_start_corrections_app: str
) -> None:
    base_url = window_start_corrections_app
    _open_window_start_corrections(page, base_url)

    reason_box = page.locator('textarea[aria-label="Reason for these corrections"]')
    reason_box.fill("Regression test: confirming deployment date against field records")

    apply_button = page.get_by_role("button", name="Apply this trap", exact=True).first
    apply_button.click()

    # This is the actual regression check: before the fix there was no
    # intermediate state to see at all - the click and the correction/save
    # happened in the same script pass, so this locator would never resolve.
    applying_button = page.get_by_role("button", name="Applying…", exact=True).first
    expect(applying_button).to_be_visible(timeout=10_000)
    expect(applying_button).to_be_disabled()

    expect(page.get_by_text("corrected.", exact=False).first).to_be_visible(timeout=30_000)


def test_confirm_bulk_apply_shows_a_disabled_applying_state_before_completing(
    page: Page, window_start_corrections_app: str
) -> None:
    base_url = window_start_corrections_app
    _open_window_start_corrections(page, base_url)

    reason_box = page.locator('textarea[aria-label="Reason for these corrections"]')
    reason_box.fill("Regression test: bulk-confirming deployment date against field records")

    # This checkbox is a react-aria Pressable component (visually-hidden
    # <input>, custom press handling on its parent <label>) that doesn't
    # reliably respond to a plain click even in real Playwright/Chromium -
    # genuine keyboard focus + Space does (same as test_bulk_activate_lock.py).
    select_checkboxes = page.get_by_role("checkbox", name="Select")
    expect(select_checkboxes.nth(1)).to_be_attached(timeout=15_000)
    select_checkboxes.nth(0).focus()
    page.keyboard.press("Space")
    expect(select_checkboxes.nth(0)).to_be_checked(timeout=10_000)
    select_checkboxes.nth(1).focus()
    page.keyboard.press("Space")
    expect(select_checkboxes.nth(1)).to_be_checked(timeout=10_000)

    page.get_by_role("button", name="Preview bulk apply", exact=True).click()
    expect(page.get_by_text("Confirm bulk correction", exact=True)).to_be_visible(timeout=15_000)

    confirm_button = page.get_by_role("button", name="Confirm bulk apply", exact=True)
    expect(confirm_button).to_be_enabled(timeout=10_000)
    confirm_button.click()

    applying_button = page.get_by_role("button", name="Applying…", exact=True).first
    expect(applying_button).to_be_visible(timeout=10_000)
    expect(applying_button).to_be_disabled()

    expect(page.get_by_text("Bulk correction applied.", exact=True)).to_be_visible(timeout=30_000)
