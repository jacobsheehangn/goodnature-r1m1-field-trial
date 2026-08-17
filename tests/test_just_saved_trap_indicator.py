"""Regression test for a field-reported bug (2026-08-17 field notes):

"After trap save doesn't land you at top of trap page so you don't see
success status and have to scroll up page as just looking at cards already
completed" / "didn't get a success status after successful trap check".

The top-of-page "<trap> saved" flash is a true one-shot: popped from
session_state (`saved_check`) the instant it's rendered, so if the operator
doesn't look at the screen before the *next* rerun - scrolling past it fast
in the field, a reconnect landing on a fresh render, anything - it's gone
for good with no second chance, and every checked card in the list looked
identical anyway, so scrolling back up wouldn't even say *which* one was
just done.

The fix adds a second, persistent signal: the just-saved trap's own card
(session_state["last_saved_trap_{visit_id}"], never popped - only replaced
by the next save) renders "✓ Just saved" with a bolder border instead of the
plain "✓ Checked" every other completed card gets, for as long as it stays
the most recent one - independent of scroll position, reruns, or whether the
one-shot flash was ever seen.
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


def _do_a_simple_check(page: Page, trap_index: int) -> str:
    """Check the Nth not-yet-checked trap on the current visit page with the
    simplest possible answers, and return its trap ID (read back from the
    workflow URL param, same as elsewhere in this test suite - simpler and
    less fragile than trying to scrape the trap ID out of the card DOM)."""
    page.get_by_role("button", name="Check", exact=True).nth(trap_index).click()
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)
    query = dict(pair.split("=") for pair in page.url.split("?", 1)[1].split("&") if "=" in pair)
    trap_id = query.get("wf_trap", "")
    page.get_by_text("Trap still set, no animal", exact=True).click()
    expect(page.get_by_role("radio", name="Trap still set, no animal", exact=True)).to_be_checked(timeout=10_000)
    expect(page.get_by_text("Trap relured, reset and ready?", exact=True)).to_be_visible(timeout=10_000)
    # Scoped to this specific radiogroup, not a bare "Yes" - some traps also
    # have a camera-check section with its own "Yes" option.
    service_group = page.get_by_role("radiogroup", name="Trap relured, reset and ready?")
    service_yes = service_group.get_by_role("radio", name="Yes", exact=True)
    service_yes.focus()
    page.keyboard.press("Space")
    expect(service_yes).to_be_checked(timeout=10_000)

    camera_group = page.get_by_role("radiogroup", name="Camera working and covering the trap?")
    if camera_group.count():
        camera_yes = camera_group.get_by_role("radio", name="Yes", exact=True)
        camera_yes.focus()
        page.keyboard.press("Space")
        expect(camera_yes).to_be_checked(timeout=10_000)

    save_button = page.get_by_role("button", name=re.compile(r"^Save check$"), exact=False)
    expect(save_button).to_be_enabled(timeout=10_000)
    save_button.click()
    expect(page.get_by_text("saved", exact=False).first).to_be_visible(timeout=30_000)
    return trap_id


def test_just_saved_trap_gets_a_distinct_persistent_indicator(
    page: Page, local_app_url: str
) -> None:
    page.goto(local_app_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Start checking", exact=False).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)

    first_trap = _do_a_simple_check(page, 0)
    expect(page.get_by_text("Just saved", exact=False)).to_be_visible(timeout=10_000)
    expect(page.get_by_text(first_trap, exact=True)).to_be_visible(timeout=10_000)

    # Trigger an ordinary rerun that does NOT go through navigate() at all -
    # exactly the situation the one-shot flash can't survive (it's popped on
    # the very first render after save, gone on anything after), but the
    # persistent per-card marker should. Toggling this filter switch is an
    # ordinary in-session interaction, not a reconnect/reload.
    # This react-aria Pressable toggle doesn't reliably respond to a plain
    # click (the same component family proven flaky for this throughout the
    # repo's test suite); genuine keyboard focus + Space does.
    filter_toggle = page.get_by_role("switch", name="Filter or search traps", exact=False)
    filter_toggle.focus()
    page.keyboard.press("Space")
    page.wait_for_timeout(500)
    assert page.get_by_text(f"{first_trap} saved", exact=True).count() == 0, (
        "the one-shot flash is expected to be gone after any further rerun - that's the whole problem this fix solves"
    )
    expect(page.get_by_text("Just saved", exact=False)).to_be_visible(timeout=10_000)

    # Now save a second trap - the *new* one should show "Just saved" and
    # the first one should have reverted to the plain "Checked" state, not
    # both showing "Just saved" at once.
    second_trap = _do_a_simple_check(page, 0)
    assert second_trap != first_trap

    just_saved_texts = page.get_by_text("Just saved", exact=False)
    expect(just_saved_texts).to_have_count(1, timeout=10_000)
    checked_texts = page.get_by_text("✓ Checked", exact=True)
    expect(checked_texts).to_have_count(1, timeout=10_000)
