"""Regression tests for a field-reported bug (2026-08-14 field notes):

A session drop right after a check was successfully saved could, on
reconnect, offer "Resume checking <trap>?" for the trap that had *just* been
saved - not an unfinished one. This confused the operator (two separate
screenshots showed it for different traps, R15-4 and R15-7) and at least
once led to a genuine duplicate Check row when they tapped Resume and
re-submitted a check for an already-done trap.

Root cause: a normal check save immediately starts a fresh monitoring window
for the same trap (see the check-save handler's will_start/start_window
call), so `open_window(trap_id) is not None` is true both for "not yet
checked" and "just finished" - validate_workflow_resume only checked the
window, never whether a Check row already existed for that trap this visit.
Separately, session_state["trap_id"] (and the URL's wf_trap) was never
cleared when navigating back to the trap-selector ("visit") page after a
save, so the stale, just-completed trap_id was exactly what a reconnecting
session would read back.

Uses dynamic (now-relative) dates throughout - a chunk of this session's
earlier tests hardcoded 2026-08-13 and broke as real time passed it; this
file is written to not repeat that.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]


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


def test_validate_workflow_resume_refuses_an_already_checked_trap(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json, app
        import pandas as pd
        from datetime import timedelta

        data = app.create_sample_data()
        trap = data["Traps"].iloc[0]
        trap_id, site_id = trap["Trap ID"], trap["Site ID"]

        visit_id = "TEST-RESUME-VISIT-1"
        vrow = {c: "" for c in app.SHEETS["Visits"]}
        vrow.update({
            "Visit ID": visit_id, "Site ID": site_id, "Status": "In progress",
            "Start Time": app.dtstr(app.now() - timedelta(hours=1)), "Operator": "Test",
        })
        data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([vrow])], ignore_index=True)

        check_id = "TEST-RESUME-CHECK-1"
        crow = {c: "" for c in app.SHEETS["Checks"]}
        crow.update({
            "Check ID": check_id, "Visit ID": visit_id, "Trap ID": trap_id,
            "Check Time": app.dtstr(app.now() - timedelta(minutes=5)), "Finding": "Trap still set, no animal",
        })
        data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([crow])], ignore_index=True)
        app.save_data(data)

        reloaded = app.load_data()
        # A fresh window is open for this trap (a normal check re-opens one
        # immediately) - exactly the state that used to be misread as "not
        # yet checked".
        already_checked_candidate = app.validate_workflow_resume(reloaded, site_id, visit_id, trap_id)

        other_trap_id = reloaded["Traps"].iloc[1]["Trap ID"]
        not_yet_checked_candidate = app.validate_workflow_resume(reloaded, site_id, visit_id, other_trap_id)

        print(json.dumps({
            "already_checked_is_none": already_checked_candidate is None,
            "not_yet_checked_is_valid": not_yet_checked_candidate is not None,
        }))
        """,
    )
    assert out["already_checked_is_none"] is True, "must refuse to resume a trap that already has a Check row this visit"
    assert out["not_yet_checked_is_valid"] is True, "must still allow resuming a genuinely unfinished trap in the same visit"


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


def test_reconnecting_after_a_completed_check_does_not_offer_to_resume_it(
    page: Page, local_app_url: str
) -> None:
    """The exact field scenario: finish a check for real, then simulate a
    dropped-and-reconnected session (fresh browser context = fresh
    WebSocket = fresh Streamlit session, same as a real reload) landing on
    the URL captured right after that save. It must NOT show "Resume
    checking?" for the trap that was just completed."""
    context1 = page.context
    page.goto(local_app_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Start checking", exact=False).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Check", exact=True).first.click()
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)

    page.get_by_text("Trap still set, no animal", exact=True).click()
    expect(page.get_by_role("radio", name="Trap still set, no animal", exact=True)).to_be_checked(timeout=10_000)

    expect(page.get_by_text("Trap relured, reset and ready?", exact=True)).to_be_visible(timeout=10_000)
    # This react-aria Pressable radio doesn't reliably respond to a plain
    # click (proven flaky for this component family throughout this repo's
    # test suite); genuine keyboard focus + Space does.
    service_yes = page.get_by_role("radio", name="Yes", exact=True)
    service_yes.focus()
    page.keyboard.press("Space")
    expect(service_yes).to_be_checked(timeout=10_000)

    save_button = page.get_by_role("button", name=re.compile(r"^Save check$"), exact=False)
    expect(save_button).to_be_enabled(timeout=10_000)
    save_button.click()
    expect(page.get_by_text("saved", exact=False).first).to_be_visible(timeout=30_000)
    page.wait_for_timeout(800)

    resume_url = page.url
    assert "wf_trap" not in resume_url, (
        f"the just-completed trap must not linger in the URL after returning to the selector, got {resume_url}"
    )

    browser = context1.browser
    context2 = browser.new_context()
    try:
        page2 = context2.new_page()
        page2.goto(resume_url, wait_until="domcontentloaded", timeout=60_000)
        page2.wait_for_timeout(1500)
        assert page2.get_by_text("Resume checking?", exact=True).count() == 0, (
            "must not offer to resume a trap that was already successfully saved"
        )
        expect(page2.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=15_000)
    finally:
        context2.close()
