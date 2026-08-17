"""Regression test for a gap found while investigating 2026-08-17 field notes.

seed_check_draft() (the draft-answer restore built in a prior fix) was only
ever called from the "Resume checking?" dialog's Resume button. But
Streamlit's own disconnected-session recovery only lasts
server.disconnectedSessionTTL (2 minutes by default) before session_state is
gone outright - plausible to exceed during a real trap service (lure change,
camera-app switch) - and even inside that window, the resume *candidate* can
fail validation for unrelated reasons. Either way, an operator can land back
on Trap sites and just tap "Check" on the same trap again through the
completely normal flow, which never goes through that dialog at all - so the
draft never got restored despite still being on disk.

The fix calls seed_check_draft() unconditionally at the top of the check
page itself (idempotent per-key, so it never clobbers a real edit). This
tests exactly that path: fill part of a form, then reach the *same* trap's
check page again via the plain Trap sites -> Start checking -> Check flow in
a brand-new browser session - no resume dialog, no URL trickery - and
confirm the answers come back anyway.
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


def test_draft_restores_via_a_plain_reopen_not_just_the_resume_dialog(
    page: Page, local_app_url: str
) -> None:
    context1 = page.context
    page.goto(local_app_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Start checking", exact=False).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
    # The visit page's own H1 is the site name (header(site_name(...), ...))
    # - capture it so context2 can target the *same* site by name below,
    # rather than relying on ".first", which isn't guaranteed to pick the
    # same card in a second, independent session (site list ordering can
    # differ run to run).
    site_name_text = page.locator("h1").first.inner_text()
    page.get_by_role("button", name="Check", exact=True).first.click()
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)

    page.get_by_text("Trap still set, no animal", exact=True).click()
    expect(page.get_by_role("radio", name="Trap still set, no animal", exact=True)).to_be_checked(timeout=10_000)

    notes_box = page.locator('textarea[aria-label="Anything else to record?"]')
    notes_box.wait_for(timeout=10_000)
    notes_box.fill("draft restore via normal reopen test")
    notes_box.press("Tab")
    page.wait_for_timeout(1000)

    # Deliberately do NOT reload/resume via the dropped-connection URL - just
    # start a brand-new browser session (a fresh WebSocket, same as this
    # operator picking up a different device, or the old session having
    # genuinely expired) and walk the completely ordinary path back to the
    # same trap.
    browser = context1.browser
    context2 = browser.new_context()
    try:
        page2 = context2.new_page()
        page2.goto(local_app_url, wait_until="domcontentloaded", timeout=60_000)
        expect(page2.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

        # The visit is still open, so this is "Resume checking" (site-level),
        # not "Start checking" - either way it's the ordinary flow, not the
        # dropped-connection dialog. Each site card renders its heading then
        # its action button with nothing else in between, so the next button
        # in DOM order after the matching heading is that card's own button
        # - simpler and less ambiguous here than matching on a wrapper div
        # (Streamlit nests several per card, breaking a has-text() filter).
        heading = page2.get_by_text(site_name_text, exact=True)
        heading.locator("xpath=following::button[1]").click()
        expect(page2.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
        page2.get_by_role("button", name="Check", exact=True).first.click()
        expect(page2.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)

        # Playwright's role-based to_be_checked() doesn't reliably read this
        # component's state (a visually-hidden native input driven by
        # react-aria - confirmed via a direct DOM check that .checked and
        # data-selected are both genuinely true, and a screenshot showing it
        # visually selected, when to_be_checked() alone said otherwise). The
        # rest of the form only renders at all once Finding has a value, so
        # that itself is proof the restore worked - assert on it directly.
        finding_radio = page2.get_by_role("radio", name="Trap still set, no animal", exact=True)
        expect(finding_radio).to_be_visible(timeout=10_000)
        assert finding_radio.evaluate("el => el.checked") is True

        expect(page2.get_by_text("Trap relured, reset and ready?", exact=True)).to_be_visible(timeout=10_000)
        restored_notes = page2.locator('textarea[aria-label="Anything else to record?"]')
        expect(restored_notes).to_have_value("draft restore via normal reopen test", timeout=10_000)
    finally:
        context2.close()
