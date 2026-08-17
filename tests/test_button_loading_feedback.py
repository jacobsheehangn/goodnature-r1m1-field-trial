"""Regression tests for a field-reported bug (2026-08-17 field notes):

Tapping "Save check" or "Check" gave no visible feedback that anything was
happening - "tap button not clear anything is happening", "tapping check and
nothing happens". Root cause, confirmed by reading Streamlit's rendering
model: a widget is only repainted on a full script rerun, and both buttons
previously did their slow work (workbook writes / navigation) in the SAME
script pass that first detected the click - so the disabled/relabeled button
state computed at the top of that pass was already stale by the time
anything slow happened, and a fresh rerun (which would show the new state)
only occurred *after* the slow part was already done and the page had moved
on.

The fix splits each button into two passes: the first rerun just
acknowledges the tap (sets a lock, reruns immediately - cheap, no I/O), so
the *next* rerun genuinely renders with the button already disabled/
relabelled before the slow work (save, or navigation) begins. This is
directly testable: before the fix there was no intermediate disabled state
to observe at all; after the fix, there is a real distinct render pass that
shows it.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
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
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_check_button_shows_a_disabled_opening_state_before_navigating(
    page: Page, local_app_url: str
) -> None:
    page.goto(local_app_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Start checking", exact=False).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)

    check_button = page.get_by_role("button", name="Check", exact=True).first
    check_button.click()

    # This is the actual regression check: before the fix, there was no
    # intermediate state to see at all - the button click and the page
    # navigation happened in the same script pass, so this locator would
    # never resolve. After the fix it's a real, distinct render (backed by a
    # deliberate short dwell in app.py - unlike Save check, opening a trap
    # has no slow work of its own to naturally create the gap).
    expect(page.get_by_role("button", name="Opening…", exact=True)).to_be_visible(timeout=10_000)

    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)


def test_save_check_button_shows_a_disabled_saving_state_before_navigating(
    page: Page, local_app_url: str
) -> None:
    page.goto(local_app_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Start checking", exact=False).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Check", exact=True).first.click()
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)

    page.get_by_text("Trap still set, no animal", exact=True).click()
    expect(page.get_by_role("radio", name="Trap still set, no animal", exact=True)).to_be_checked(timeout=10_000)

    expect(page.get_by_text("Trap relured, reset and ready?", exact=True)).to_be_visible(timeout=10_000)
    service_yes = page.get_by_role("radio", name="Yes", exact=True)
    service_yes.focus()
    page.keyboard.press("Space")
    expect(service_yes).to_be_checked(timeout=10_000)

    save_button = page.get_by_role("button", name=re.compile(r"^Save check$"), exact=False)
    expect(save_button).to_be_enabled(timeout=10_000)
    save_button.click()

    # As above: the whole point of the fix is that this state now genuinely
    # exists as its own render, not just a same-pass value that gets
    # overwritten before the browser ever sees it.
    expect(page.get_by_role("button", name="Saving…", exact=True)).to_be_visible(timeout=10_000)
    expect(page.get_by_role("button", name="Saving…", exact=True)).to_be_disabled()

    expect(page.get_by_text("saved", exact=False).first).to_be_visible(timeout=30_000)
