"""Regression tests for the Tier 2 follow-up to the 2026-08-17 field-notes
button-feedback fix (see tests/test_button_loading_feedback.py for the
original Check/Save check fix and its root-cause explanation).

The user's field report was specific to Save check, but the same root cause
(Streamlit only repaints a widget on a fresh script rerun, so a button that
does its slow work in the same pass it detects the click never shows a real
disabled/busy state) applies to every other consequential save button in the
app. This file covers the three buttons that needed the shared
`two_phase_button()` helper applied on a follow-up pass:

- Necropsy evidence correction's "Save correction" (goes through
  commit_staged_records_with_photos, so it also needs the caller-managed
  persistent lock, same as Save check itself and the Necropsy review save).
- Window start-time correction's "Apply this trap" (single-trap apply).
- Window start-time correction's "Confirm bulk apply" (bulk apply).
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


def _select_streamlit_option(page: Page, combobox, filter_text: str, exact: bool = True) -> None:
    combobox.click()
    page.keyboard.type(filter_text)
    if exact:
        page.get_by_role("option", name=filter_text, exact=True).click()
    else:
        page.get_by_role("option", name=filter_text, exact=False).first.click()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed_and_launch(tmp_path: Path, seed_script: str):
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
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(seed_script)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    seeded = json.loads(result.stdout.strip().splitlines()[-1])

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
        yield url, data_dir, seeded
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture
def necropsy_window_app(tmp_path: Path):
    seed = """
        import json, app, pandas as pd
        data = app.create_sample_data()
        trap = data["Traps"].iloc[0]
        window_id = "TEST-NEC-WINDOW-1"
        row = {c: "" for c in app.SHEETS["Windows"]}
        row.update({
            "Window ID": window_id, "Trap ID": trap["Trap ID"], "Product": trap["Product"],
            "Build Version": trap["Build Version"], "Site ID": trap["Site ID"], "Status": "Closed",
            "Start Time": "2026-08-01 00:00:00", "End Time": "2026-08-02 00:00:00",
            "Finding At Close": "Dead animal found", "Necropsy Status": "Complete",
            "Necropsy Assessment": "Supports humane kill", "Final Humane Kill": "Yes",
            "Animal Weight Range": "101-150g", "Species": "Rat", "Rat Type": "Norway rat",
        })
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([row])], ignore_index=True)
        app.save_data(data)
        print(json.dumps({"window_id": window_id, "trap_id": trap["Trap ID"], "site_id": trap["Site ID"]}))
    """
    yield from _seed_and_launch(tmp_path, seed)


def test_necropsy_correction_save_shows_a_disabled_saving_state_before_navigating(
    page: Page, necropsy_window_app
) -> None:
    base_url, data_dir, seeded = necropsy_window_app

    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Administration", exact=False).click()
    page.get_by_role("link", name="Data & records", exact=True).click()
    expect(page.get_by_text("Data & records", exact=True).last).to_be_visible(timeout=30_000)

    _select_streamlit_option(page, page.get_by_role("combobox", name="Record type"), "Necropsy evidence")
    window_picker = page.get_by_role("combobox", name="Select closed test window")
    expect(window_picker).to_be_visible(timeout=15_000)
    _select_streamlit_option(page, window_picker, seeded["window_id"], exact=False)

    # A real, consistency-passing field change (not just leaving everything as
    # seeded) so this exercises the actual commit_staged_records_with_photos
    # path the persistent-lock treatment exists for, not the early-return
    # "no values changed" branch.
    species_picker = page.get_by_role("combobox", name="Species", exact=True)
    expect(species_picker).to_be_visible(timeout=15_000)
    _select_streamlit_option(page, species_picker, "Mouse")

    reason_box = page.locator('textarea[aria-label="Correction reason"]')
    reason_box.fill("Regression test: two-phase save feedback")

    save_button = page.get_by_role("button", name="Save correction", exact=True)
    save_button.click()

    # The point of this test: before the two_phase_button fix, this button did
    # its work (including a workbook write) in the same script pass that
    # detected the click, so there was no real intermediate disabled render to
    # observe here at all.
    expect(page.get_by_role("button", name="Saving…", exact=True)).to_be_visible(timeout=10_000)
    expect(page.get_by_role("button", name="Saving…", exact=True)).to_be_disabled()

    expect(page.get_by_text("Correction saved.", exact=True)).to_be_visible(timeout=30_000)


@pytest.fixture
def suspect_r1_window_app(tmp_path: Path):
    """A single R1 trap whose only window's Start Time falls on a different
    calendar day than its Deployment Start - the exact signature
    suspect_earliest_window_candidates() flags, and the only way to reach the
    Window start-time correction tools' Apply/Confirm buttons at all."""
    seed = """
        import json, app, pandas as pd
        data = app.create_sample_data()
        r1_traps = data["Traps"][data["Traps"]["Product"] == "R1"]
        trap = r1_traps.iloc[0]
        trap_id = trap["Trap ID"]

        # create_sample_data() can seed other R1 traps that also happen to
        # look "suspect" (earliest-window date != Deployment Start date) -
        # neutralize every other one so this fixture yields exactly one
        # candidate, the one this test deliberately sets up below.
        for _, t in r1_traps.iterrows():
            other_id = t["Trap ID"]
            if other_id == trap_id:
                continue
            other_windows = data["Windows"][data["Windows"]["Trap ID"] == other_id]
            if other_windows.empty:
                continue
            earliest = other_windows.sort_values("Start Time").iloc[0]
            oidx = data["Traps"].index[data["Traps"]["Trap ID"] == other_id][0]
            data["Traps"].at[oidx, "Deployment Start"] = earliest["Start Time"]

        tidx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
        data["Traps"].at[tidx, "Deployment Start"] = "2026-08-01 00:00:00"
        # Drop any windows create_sample_data() already gave this trap so the
        # single injected window below is unambiguously the earliest one.
        data["Windows"] = data["Windows"][data["Windows"]["Trap ID"] != trap_id].reset_index(drop=True)
        window_id = "TEST-WINFIX-WINDOW-1"
        wrow = {c: "" for c in app.SHEETS["Windows"]}
        wrow.update({
            "Window ID": window_id, "Trap ID": trap_id, "Product": trap["Product"],
            "Build Version": trap["Build Version"], "Site ID": trap["Site ID"], "Status": "Open",
            "Start Time": "2026-08-05 09:00:00", "Review Status": "Not required",
        })
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([wrow])], ignore_index=True)
        app.save_data(data)
        print(json.dumps({"trap_id": trap_id, "window_id": window_id, "site_id": trap["Site ID"]}))
    """
    yield from _seed_and_launch(tmp_path, seed)


def _open_window_start_corrections(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Administration", exact=False).click()
    page.get_by_role("link", name="Data & records", exact=True).click()
    expect(page.get_by_text("Data & records", exact=True).last).to_be_visible(timeout=30_000)
    page.get_by_text("Window start corrections", exact=True).click()
    expect(page.get_by_text("Flagged traps", exact=True)).to_be_visible(timeout=15_000)


def _click_until_busy_or_done(
    page: Page, button, busy_label: str, done_needle: str, attempts: int = 6, per_attempt_s: float = 1.5
) -> bool:
    """Click `button` repeatedly until either its busy label appears (with
    the button itself disabled - checked together, in the same poll
    iteration, to avoid a second round-trip racing past a brief state) or
    the flow's terminal text appears. Returns True if the busy state was
    observed, False if only the terminal state was (still passes the
    underlying regression - see comment below - but is worth knowing).

    The retry-until-something-happens shape here is needed only because of
    a pre-existing Streamlit/BaseWeb quirk unrelated to two_phase_button: a
    click issued shortly after committing a nearby text_area edit can be
    swallowed with no server response at all, and how many clicks that
    takes before one lands is not fully deterministic (confirmed by tracing
    raw WebSocket frames - the swallowed click sends a frame but gets no
    response back). Real touch input naturally has more separation than a
    scripted fill()+click(), so this is unlikely to bite a field operator
    the way it bites a fast scripted click; flagged separately, not fixed
    here."""
    deadline_check = f"""() => {{
        const btns = [...document.querySelectorAll('button')];
        const busy = btns.find(b => b.textContent.includes({busy_label!r}));
        if (busy) return {{state: 'busy', disabled: busy.disabled}};
        if (document.body.innerText.includes({done_needle!r})) return {{state: 'done'}};
        return null;
    }}"""
    for _ in range(attempts):
        button.click()
        attempt_deadline = time.monotonic() + per_attempt_s
        while time.monotonic() < attempt_deadline:
            result = page.evaluate(deadline_check)
            if result and result["state"] == "busy":
                assert result["disabled"], "the busy-state button should be disabled"
                return True
            if result and result["state"] == "done":
                return False
    raise AssertionError(f"neither {busy_label!r} nor {done_needle!r} appeared after {attempts} click attempts")


def test_apply_this_trap_shows_a_disabled_applying_state_before_navigating(
    page: Page, suspect_r1_window_app
) -> None:
    base_url, data_dir, seeded = suspect_r1_window_app
    _open_window_start_corrections(page, base_url)

    page.get_by_label("Reason for these corrections").fill("Regression test: single-apply feedback")
    # Pre-existing Streamlit/BaseWeb quirk, unrelated to two_phase_button:
    # a click issued immediately after committing the reason text_area's
    # edit can be swallowed with no server response at all (confirmed by
    # tracing raw WebSocket frames). Letting that edit's own rerun settle
    # first avoids racing it - real touch input naturally has more
    # separation than a scripted fill()+click(), so this is unlikely to
    # bite a field operator the way it can bite a fast scripted click;
    # flagged separately, not fixed here.
    page.wait_for_timeout(1_500)

    apply_button = page.get_by_role("button", name="Apply this trap", exact=True)

    # Same regression class as Save check/Save correction: before the fix
    # this button's work (a workbook write via correct_window_start +
    # save_data) happened in the same pass as the click, so there was no
    # observable intermediate state.
    saw_busy = _click_until_busy_or_done(page, apply_button, "Applying", "No change")
    assert saw_busy, "the busy 'Applying…' state was never observed"


def test_confirm_bulk_apply_shows_a_disabled_applying_state_before_navigating(
    page: Page, suspect_r1_window_app
) -> None:
    base_url, data_dir, seeded = suspect_r1_window_app
    _open_window_start_corrections(page, base_url)

    page.get_by_label("Reason for these corrections").fill("Regression test: bulk-apply feedback")

    # This checkbox is a react-aria Pressable, which doesn't reliably respond
    # to a plain click/.check() anywhere in this repo's test suite - genuine
    # keyboard focus + Space is the established, reliable workaround.
    select_checkbox = page.get_by_role("checkbox", name="Select", exact=True)
    select_checkbox.focus()
    page.keyboard.press("Space")
    expect(select_checkbox).to_be_checked(timeout=10_000)

    page.get_by_role("button", name="Preview bulk apply", exact=True).click()
    expect(page.get_by_text("Confirm bulk correction", exact=True)).to_be_visible(timeout=15_000)

    confirm_button = page.get_by_role("button", name="Confirm bulk apply", exact=True)
    saw_busy = _click_until_busy_or_done(page, confirm_button, "Applying", "Bulk correction applied.")
    assert saw_busy, "the busy 'Applying…' state was never observed"

    expect(page.get_by_text("Bulk correction applied.", exact=True)).to_be_visible(timeout=30_000)
