"""Regression test for a 2026-08-17/18 field-notes follow-up:

Design conversation on item 7 (the camera check disrupting the check-form
flow) concluded that reordering the form wasn't viable (Camera check has to
stay after Trap service), so the remaining lever was making the *return*
from the Arlo app-switch land you exactly back where you left off, not the
top of the form - "focus directly where you left off".

The check-form draft already restores every answered field on resume (see
test_check_draft_persistence.py / test_check_draft_restores_on_normal_reopen.py) -
this specifically tests that the page also *scrolls* to the Camera check
section (the one field that actually caused the interruption) the moment a
draft is restored, rather than leaving the operator to scroll down through
an already-mostly-filled-in form to find where they left off.
"""
from __future__ import annotations

import os
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


def test_resuming_a_camera_trap_scrolls_to_the_camera_check_section(
    page: Page, local_app_url: str
) -> None:
    context1 = page.context
    page.goto(local_app_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Start checking", exact=False).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)

    # Find a camera-equipped trap - not every seeded trap has one.
    camera_trap_found = False
    for idx in range(5):
        page.get_by_role("button", name="Check", exact=True).nth(idx).click()
        expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)
        page.get_by_text("Trap still set, no animal", exact=True).click()
        page.wait_for_timeout(300)
        if page.get_by_text("Camera working and covering the trap?", exact=True).count():
            camera_trap_found = True
            break
        page.get_by_role("button", name="Back to trap selector", exact=False).click()
        expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
    assert camera_trap_found, "none of the first 5 seeded traps have a camera - test setup assumption failed"

    service_group = page.get_by_role("radiogroup", name="Trap relured, reset and ready?")
    service_yes = service_group.get_by_role("radio", name="Yes", exact=True)
    service_yes.focus()
    page.keyboard.press("Space")
    expect(service_yes).to_be_checked(timeout=10_000)

    resume_url = page.url
    browser = context1.browser
    context2 = browser.new_context()
    try:
        page2 = context2.new_page()
        page2.set_viewport_size({"width": 390, "height": 844})
        page2.goto(resume_url, wait_until="domcontentloaded", timeout=60_000)
        expect(page2.get_by_text("Resume checking?", exact=True)).to_be_visible(timeout=15_000)
        page2.get_by_role("button", name="Resume", exact=True).click()
        expect(page2.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)
        page2.wait_for_timeout(1200)

        anchor_top = page2.evaluate(
            """() => {
              const el = document.getElementById('r1m1-camera-check-anchor');
              return el ? el.getBoundingClientRect().top : null;
            }"""
        )
        assert anchor_top is not None, "the Camera check anchor should exist on this trap's form"
        assert 0 <= anchor_top <= 400, (
            f"expected the page to land scrolled to the Camera check section, anchor was at y={anchor_top}"
        )
        expect(page2.get_by_text("Camera check", exact=True)).to_be_in_viewport(timeout=5_000)
    finally:
        context2.close()
