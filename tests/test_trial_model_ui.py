"""Phase 1 (TRIAL_LIFECYCLE_BRIEF.md): the screens the Trial model touches.

Drives the real app in a browser for what the logic tests cannot reach: the
Add trap form (always Inactive, no deployment date), the Edit form (never
stamps "now" on a blank Deployment Start), the bulk-activate expander at a site
with no trial, and a real check save that must stamp the open trial - and must
still save when the trial lookup fails."""
from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = "field_trial_data_v8_6_5.xlsx"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def _serve(data_dir: Path, seed: str, extra_env: dict | None = None):
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
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(seed)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr[-3000:]}"
    env.update(extra_env or {})
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.address", "127.0.0.1", "--server.port", str(port),
            "--server.headless", "true", "--browser.gatherUsageStats", "false",
        ],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    try:
        while True:
            if process.poll() is not None:
                raise RuntimeError("Local Streamlit process exited before becoming ready.")
            try:
                with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except Exception:
                if time.monotonic() > deadline:
                    raise RuntimeError("Local Streamlit app did not become ready within 60 seconds.")
                time.sleep(0.25)
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _sheet(data_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_excel(data_dir / WORKBOOK, sheet_name=name, dtype=str).fillna("")


def _open_trap_setup(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Administration", exact=False).click()
    page.get_by_role("link", name="Trial setup", exact=True).click()
    expect(page.get_by_text("What do you need to manage?", exact=True)).to_be_visible(timeout=30_000)


# A site with no trial and one trap that was staged but never activated (blank
# Deployment Start), plus the sample's own traps (stored Deployment Start).
_SEED_STAGED = """
    import app
    data = app.create_sample_data()
    site = data["Sites"].iloc[0]["Site ID"]
    row = {c: "" for c in app.SHEETS["Traps"]}
    row.update({"Trap ID": "TEST-STAGED-1", "Product": "R1", "Build Version": "R1 Build 4.3", "Site ID": site,
                "Route Order": "40", "Location": "Staged location", "Status": "Inactive", "Deployment Start": ""})
    import pandas as pd
    data["Traps"] = pd.concat([data["Traps"], pd.DataFrame([row])], ignore_index=True)
    app.save_data(data)
"""


def test_add_trap_creates_an_inactive_trap_with_no_deployment_date_and_no_window(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _serve(data_dir, _SEED_STAGED) as url:
        _open_trap_setup(page, url)
        windows_before = len(_sheet(data_dir, "Windows"))
        page.get_by_role("button", name="Add trap", exact=True).click()
        expect(page.get_by_role("heading", name="Add trap")).to_be_visible(timeout=15_000)

        # No way to ask for an Active trap or a deployment date when adding.
        expect(page.get_by_text("New traps start Inactive. Activate the trap when a trial starts.", exact=True)).to_be_visible()
        assert page.get_by_text("Deployment start date", exact=True).count() == 0
        assert page.get_by_text("Deployment start time", exact=True).count() == 0
        assert page.get_by_label("Status", exact=True).count() == 0

        page.get_by_label("Trap ID", exact=True).fill("TEST-NEW-1")
        page.get_by_label("Location description").fill("By the gate")
        page.get_by_role("button", name="Add trap", exact=True).last.click()
        expect(page.get_by_text("TEST-NEW-1 added.", exact=True)).to_be_visible(timeout=20_000)
        expect(page.get_by_text("The trap was added as inactive. Activate it when a trial starts.", exact=True)).to_be_visible()

    traps = _sheet(data_dir, "Traps")
    new = traps[traps["Trap ID"] == "TEST-NEW-1"].iloc[0]
    assert new["Status"] == "Inactive" and new["Deployment Start"] == ""
    windows = _sheet(data_dir, "Windows")
    assert len(windows) == windows_before and (windows["Trap ID"] == "TEST-NEW-1").sum() == 0, "adding a trap must not open a window"


def test_editing_a_never_activated_trap_keeps_its_deployment_start_blank(page: Page, tmp_path: Path) -> None:
    """The latent bug the brief calls out: an edit that defaults a blank
    Deployment Start to today and writes it back would silently stamp 'now' on
    every staged trap. The Edit button in the trap list opens the trap_edit
    page, so that is the path exercised here."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _serve(data_dir, _SEED_STAGED) as url:
        stored = _sheet(data_dir, "Traps")
        other = stored[(stored["Trap ID"] != "TEST-STAGED-1") & (stored["Deployment Start"] != "")].iloc[0]
        _open_trap_setup(page, url)

        for trap_id, new_location in (("TEST-STAGED-1", "Fixed location"), (other["Trap ID"], "Other fixed location")):
            page.locator(f".st-key-setup_edit_trap_{trap_id} button").click()
            expect(page.get_by_role("heading", name=f"Edit {trap_id}")).to_be_visible(timeout=20_000)
            page.get_by_label("Location description").fill(new_location)
            page.get_by_role("button", name="Save changes", exact=True).click()
            expect(page.get_by_text(f"{trap_id} updated.", exact=True)).to_be_visible(timeout=20_000)

    traps = _sheet(data_dir, "Traps").set_index("Trap ID")
    assert traps.loc["TEST-STAGED-1", "Location"] == "Fixed location"
    assert traps.loc["TEST-STAGED-1", "Deployment Start"] == "", "an edit must never substitute now() for a blank Deployment Start"
    assert traps.loc[other["Trap ID"], "Location"] == "Other fixed location"
    assert traps.loc[other["Trap ID"], "Deployment Start"] == other["Deployment Start"], "a stored value is written back untouched"


def test_bulk_activate_at_a_site_with_no_trial_says_so_up_front(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _serve(data_dir, _SEED_STAGED) as url:
        _open_trap_setup(page, url)
        site_name = str(_sheet(data_dir, "Sites").iloc[0]["Site Name"])
        site_box = page.get_by_label("Show traps from")
        site_box.click()
        page.get_by_role("option", name=site_name, exact=True).click()
        expander = page.get_by_text("Bulk activate traps (1 inactive)", exact=True)
        expect(expander).to_be_visible(timeout=15_000)
        expander.click()
        expect(
            page.get_by_text(f"No trial is running at {site_name}. Start a trial first. Every active trap belongs to a trial.", exact=True)
        ).to_be_visible(timeout=15_000)
        # Nothing to select or preview while the site has no trial.
        assert page.get_by_role("button", name="Preview activation", exact=True).count() == 0
        expect(page.get_by_role("button", name="Start a trial", exact=True)).to_be_visible()
        page.get_by_role("button", name="Start a trial", exact=True).click()
        expect(page.get_by_text("Builds this trial compares", exact=True)).to_be_visible(timeout=20_000)


_SEED_TRIALS_EVERYWHERE = """
    import datetime, app
    data = app.create_sample_data()
    for site in data["Sites"]["Site ID"]:
        app.create_trial(data, site, ["R1 · R1 Build 4.3"], datetime.datetime(2026, 9, 1, 8, 0))
    app.save_data(data)
"""


def _save_a_routine_check(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Start checking").first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Check", exact=True).nth(2).click()  # a trap with no camera
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=20_000)
    page.get_by_role("radio", name="Trap still set, no animal").check(force=True)
    page.get_by_role("radio", name="Yes").first.check(force=True)
    page.get_by_role("button", name="Save check").click()
    expect(page.get_by_text("✓ Just saved", exact=True)).to_be_visible(timeout=30_000)


def _restarted_window_for_the_check(data_dir: Path) -> tuple[pd.Series, pd.Series]:
    checks = _sheet(data_dir, "Checks")
    assert len(checks) == 1, "the check must have been saved"
    windows = _sheet(data_dir, "Windows")
    trap_id = checks.iloc[0]["Trap ID"]
    mine = windows[windows["Trap ID"] == trap_id]
    closed = mine[mine["Window ID"] == checks.iloc[0]["Window Closed"]]
    opened = mine[mine["Status"] == "Open"]
    assert len(closed) == 1 and len(opened) == 1, "one window closed by the check, one restarted"
    return closed.iloc[0], opened.iloc[0]


def test_a_check_save_restarts_the_window_stamped_with_the_sites_open_trial(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _serve(data_dir, _SEED_TRIALS_EVERYWHERE) as url:
        _save_a_routine_check(page, url)
    _closed, opened = _restarted_window_for_the_check(data_dir)
    assert opened["Trial ID"] == f"TRIAL-{opened['Site ID']}-01"


def test_a_check_still_saves_and_restarts_its_window_when_the_trial_lookup_fails(page: Page, tmp_path: Path) -> None:
    """The highest-risk change in the brief: start_window() runs inside the
    check-save flow. Force the trial lookup to fail (test-only hook in the
    server process) and confirm the operator still gets a saved check and a
    fresh window - unstamped."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _serve(data_dir, _SEED_TRIALS_EVERYWHERE, {"R1M1_TEST_FORCE_TRIAL_LOOKUP_FAILURE": "1"}) as url:
        _save_a_routine_check(page, url)
    _closed, opened = _restarted_window_for_the_check(data_dir)
    assert opened["Trial ID"] == "", "the window is opened, left unstamped"
    assert opened["Status"] == "Open"


# Site 1 has an Open trial declaring only R1 Build 4.3 (so R1-MAN-001 is Active inside it);
# site 2 has no trial and a staged, Inactive trap.
_SEED_BLOCKED_STATES = """
    import datetime, app, pandas as pd
    data = app.create_sample_data()
    site_a, site_b = data["Sites"].iloc[0]["Site ID"], data["Sites"].iloc[1]["Site ID"]
    app.create_trial(data, site_a, ["R1 · R1 Build 4.3"], datetime.datetime(2026, 9, 1, 8, 0))
    row = {c: "" for c in app.SHEETS["Traps"]}
    row.update({"Trap ID": "TEST-STAGED-2", "Product": "R1", "Build Version": "R1 Build 4.3", "Site ID": site_b,
                "Route Order": "40", "Location": "Staged", "Status": "Inactive"})
    data["Traps"] = pd.concat([data["Traps"], pd.DataFrame([row])], ignore_index=True)
    app.save_data(data)
"""


def _open_trap_edit(page: Page, url: str, trap_id: str) -> None:
    _open_trap_setup(page, url)
    page.locator(f".st-key-setup_edit_trap_{trap_id} button").click()
    expect(page.get_by_role("heading", name=f"Edit {trap_id}")).to_be_visible(timeout=20_000)


def _tick(page: Page, label: str) -> None:
    box = page.get_by_role("checkbox", name=label, exact=True)
    box.focus()
    page.keyboard.press("Space")
    expect(box).to_be_checked(timeout=10_000)


def test_blocked_actions_show_the_exact_message_and_change_nothing(page: Page, tmp_path: Path) -> None:
    """Every refusal reaches the operator as a plain error (ValueError -> st.error)
    and leaves the workbook as it was."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _serve(data_dir, _SEED_BLOCKED_STATES) as url:
        before = {name: _sheet(data_dir, name) for name in ("Traps", "Windows", "Trials")}

        # An Active trap inside the open trial: build cannot change, and it cannot move.
        _open_trap_edit(page, url, "R1-MAN-001")
        page.locator("summary", has_text="Change build").click()
        page.get_by_label("Reason for build change").fill("try it")
        _tick(page, "Close the current window and start a new window on this build")
        page.get_by_role("button", name="Change build", exact=True).click()
        expect(page.get_by_text("A build can't change inside a trial. Changing a build starts a new trial.", exact=False)).to_be_visible(timeout=20_000)
        expect(page.get_by_text("End TRIAL-MAN-01, then start a new trial with the builds you want", exact=False)).to_be_visible()
        expect(page.get_by_role("button", name="Go to trial", exact=True)).to_be_visible()

        toggle = page.get_by_role("switch", name="Move trap")
        toggle.focus()
        page.keyboard.press("Space")
        expect(toggle).to_be_checked(timeout=10_000)
        page.get_by_label("Reason for move").fill("try it")
        _tick(page, "Move this trap to the destination site (a trap that is Inactive has no window, so none is opened)")
        page.get_by_role("button", name="Move trap", exact=True).click()
        expect(page.get_by_text("Deactivate this trap before moving it. Leaving a trial ends its part in it.", exact=False)).to_be_visible(timeout=20_000)

        # An Inactive trap at a site with no trial: activation is refused.
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        _open_trap_edit(page, url, "TEST-STAGED-2")
        expect(page.get_by_text("Allowed while the trap is Inactive", exact=False)).to_be_hidden()  # only inside the open Change build expander
        page.locator("summary", has_text="Activate trap").click()
        page.get_by_label("Reason for activation").fill("try it")
        _tick(page, "Start a new monitoring window and set this trap to Active")
        page.get_by_role("button", name="Activate trap", exact=True).click()
        expect(page.get_by_text("Start a trial first. Every active trap belongs to a trial.", exact=False)).to_be_visible(timeout=20_000)
        expect(page.get_by_role("button", name="Start a trial", exact=True)).to_be_visible()

        # The staged-build caption shows on an Inactive trap.
        page.locator("summary", has_text="Change build").click()
        expect(page.get_by_text("Allowed while the trap is Inactive — this is how builds are staged before a trial. No monitoring window is opened.", exact=True)).to_be_visible(timeout=10_000)

    for name, frame in before.items():
        pd.testing.assert_frame_equal(_sheet(data_dir, name), frame, obj=f"{name} after refused actions")
