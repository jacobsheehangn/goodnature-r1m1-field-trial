"""Regression tests for the "Resume checking restores position, not answers"
finding from the 2026-08-13 UX audit.

Before this fix, "Resume checking?" (shown after a real session loss - not a
brief WebSocket reconnect, which Streamlit already handles fine) restored
navigation position, Bag ID and already-uploaded photos, but Finding, Species,
Rat type, Condition, Camera check and Notes lived only in ephemeral
session_state with no disk backing - the operator had to retype the whole
form. The fix persists those answers to a small JSON file alongside the
existing photo-transaction manifest (same per-check directory, same
deterministic check ID, same cleanup lifecycle), and seeds them back into
session_state at the one moment guaranteed to be a genuinely fresh session:
when "Resume" is clicked.

Covers both layers: the pure save/load round-trip in photo_integrity.py, and
the real end-to-end flow (fill part of a check form, simulate a dropped
session by opening the same resume URL in a brand-new browser context, click
Resume, confirm the form comes back pre-filled) via Playwright.
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


def test_save_and_load_draft_answers_round_trip(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json
        import photo_integrity as pi

        import os as _os
        data_root = __import__("pathlib").Path(_os.environ["R1M1_DATA_DIR"])
        check_id = "TEST-DRAFT-CHECK-1"
        pi.save_draft_answers(data_root, check_id, {"finding": "Dead animal found", "notes": "hello"})
        loaded = pi.load_draft_answers(data_root, check_id)
        print(json.dumps({"loaded": loaded}))
        """,
    )
    assert out["loaded"] == {"finding": "Dead animal found", "notes": "hello"}


def test_load_draft_answers_missing_file_returns_empty(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json
        import photo_integrity as pi

        import os as _os
        data_root = __import__("pathlib").Path(_os.environ["R1M1_DATA_DIR"])
        loaded = pi.load_draft_answers(data_root, "NEVER-SAVED-CHECK")
        print(json.dumps({"loaded": loaded}))
        """,
    )
    assert out["loaded"] == {}


def test_load_draft_answers_corrupt_file_returns_empty_not_raise(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json
        import photo_integrity as pi

        import os as _os
        data_root = __import__("pathlib").Path(_os.environ["R1M1_DATA_DIR"])
        check_id = "TEST-DRAFT-CHECK-CORRUPT"
        path = pi.draft_answers_path(data_root, check_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json{{{", encoding="utf-8")
        loaded = pi.load_draft_answers(data_root, check_id)
        print(json.dumps({"loaded": loaded}))
        """,
    )
    assert out["loaded"] == {}


def test_transaction_cleanup_removes_the_draft_file_too(tmp_path: Path) -> None:
    """delete_transaction() already handled photo cleanup; confirm the same
    call also removes the sibling draft_answers.json, so a successful check
    save doesn't leave a stray draft file behind indefinitely."""
    out = _run(
        tmp_path,
        """
        import json
        import photo_integrity as pi

        import os as _os
        data_root = __import__("pathlib").Path(_os.environ["R1M1_DATA_DIR"])
        check_id = "TEST-DRAFT-CHECK-CLEANUP"
        pi.save_draft_answers(data_root, check_id, {"finding": "Dead animal found"})
        existed_before = pi.draft_answers_path(data_root, check_id).exists()
        pi.delete_transaction(data_root, check_id)
        existed_after = pi.draft_answers_path(data_root, check_id).exists()
        print(json.dumps({"existed_before": existed_before, "existed_after": existed_after}))
        """,
    )
    assert out["existed_before"] is True
    assert out["existed_after"] is False


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


def test_resume_after_a_fresh_session_restores_finding_and_notes(
    page: Page, local_app_url: str
) -> None:
    """A fresh browser context simulates a real dropped session (a new
    WebSocket connection, exactly what Streamlit gives a reloaded/reopened
    tab) - not just a rerun within the same session, which was never the
    gap this finding described."""
    context1 = page.context
    page.goto(local_app_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Start checking", exact=False).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Check", exact=True).first.click()
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)

    page.get_by_text("Trap still set, no animal", exact=True).click()
    expect(page.get_by_role("radio", name="Trap still set, no animal", exact=True)).to_be_checked(timeout=10_000)

    notes_box = page.locator('textarea[aria-label="Anything else to record?"]')
    notes_box.wait_for(timeout=10_000)
    notes_box.fill("resume draft regression test notes")
    notes_box.press("Tab")  # blur, so Streamlit actually processes the change and reruns
    page.wait_for_timeout(1000)

    resume_url = page.url
    assert "wf_page=check" in resume_url, f"expected workflow query params in the URL, got {resume_url}"

    browser = context1.browser
    context2 = browser.new_context()
    try:
        page2 = context2.new_page()
        page2.goto(resume_url, wait_until="domcontentloaded", timeout=60_000)
        expect(page2.get_by_text("Resume checking?", exact=True)).to_be_visible(timeout=15_000)
        page2.get_by_role("button", name="Resume", exact=True).click()
        expect(page2.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)

        expect(page2.get_by_role("radio", name="Trap still set, no animal", exact=True)).to_be_checked(timeout=10_000)
        restored_notes = page2.locator('textarea[aria-label="Anything else to record?"]')
        expect(restored_notes).to_have_value("resume draft regression test notes", timeout=10_000)
    finally:
        context2.close()
