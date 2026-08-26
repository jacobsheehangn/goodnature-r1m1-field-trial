"""Regression test for a 2026-08-26 field report:

A trap with prior window history that lost its open window (e.g. via
"Unable to check", or an administrative Move+Deactivate during a site
reorg) dead-ended on "This trap has no active test window" with a "Start
window and continue"/"Start missing window" button that could never
actually work - repair_missing_window() correctly refuses to guess an
effective time once a trap has history (silently reusing "now" or the
original deployment time could misrepresent when the trap actually went
back into service), but nothing in the UI ever offered a way to actually
supply one. The only prior workaround was a Deactivate-then-Activate round
trip in Administration - functional, but it leaves a fake "deactivated then
reactivated" pair in the audit log for a trap that was never actually
pulled from the field.

The fix: when a trap with history has no open window, the check page now
asks for the effective date/time and a reason right there, and calls
repair_missing_window() with them - no Status change, no misleading audit
trail, and no detour through a different admin page.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
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


def _seed_and_launch(tmp_path: Path, seed_script: str):
    import json
    import textwrap

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
def stranded_trap_app(tmp_path: Path):
    # Mirrors the real-world shape: an Active trap with a closed historical
    # window and no open one - e.g. left behind by "Unable to check" before
    # the fix, or a Move+Deactivate during a site reorg.
    seed = """
        import json, app, pandas as pd
        data = app.create_sample_data()
        # Trap cards sort by Trap ID text, not seed order - "M1-MAN-004" is
        # the only M1 trap on this site and sorts before every "R1-MAN-*"
        # one, so it's reliably the first Check button on the page.
        trap = data["Traps"][data["Traps"]["Trap ID"] == "M1-MAN-004"].iloc[0]
        trap_id = trap["Trap ID"]
        data["Windows"] = data["Windows"][data["Windows"]["Trap ID"] != trap_id].copy()
        wrow = {c: "" for c in app.SHEETS["Windows"]}
        wrow.update({
            "Window ID": "TEST-STRANDED-W1", "Trap ID": trap_id, "Product": trap["Product"],
            "Build Version": trap["Build Version"], "Site ID": trap["Site ID"], "Status": "Closed",
            "Start Time": "2026-08-01 00:00:00", "End Time": "2026-08-20 00:00:00",
            "Finding At Close": "Unable to check", "Review Status": "Not required",
        })
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([wrow])], ignore_index=True)
        app.save_data(data)
        print(json.dumps({"trap_id": trap_id, "site_id": trap["Site ID"]}))
    """
    yield from _seed_and_launch(tmp_path, seed)


def test_a_trap_with_history_can_reopen_its_window_inline_with_a_real_effective_time(
    page: Page, stranded_trap_app
) -> None:
    base_url, data_dir, seeded = stranded_trap_app
    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    # "Mangaroa Farm" (site MAN) is create_sample_data()'s first seeded site,
    # so it's the first "Start checking" button, same as every other test in
    # this suite relies on for its own first site.
    page.get_by_role("button", name="Start checking", exact=False).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Check", exact=True).first.click()
    expect(page.get_by_text("This trap has no active test window.", exact=True)).to_be_visible(timeout=30_000)
    query = dict(pair.split("=") for pair in page.url.split("?", 1)[1].split("&") if "=" in pair)
    assert query.get("wf_trap", "") == seeded["trap_id"], (
        f"expected the first Check button to open {seeded['trap_id']!r}, got {query.get('wf_trap')!r} - "
        "trap card sort order may have changed"
    )

    # The core regression check: a trap with history must get a real effective
    # time input, not a button that can only ever fail.
    expect(page.get_by_text("This trap has prior history", exact=False)).to_be_visible(timeout=10_000)
    reason_box = page.get_by_role("textbox", name="Reason", exact=True)
    expect(reason_box).to_be_visible(timeout=10_000)

    start_button = page.get_by_role("button", name="Start window and continue", exact=True)
    start_button.click()
    expect(page.get_by_text("Enter a reason before starting the window.", exact=True)).to_be_visible(timeout=10_000)

    reason_box.fill("Trap confirmed still in place during line check - recording retroactively.")
    page.keyboard.press("Tab")
    expect(start_button).to_be_enabled(timeout=10_000)
    start_button.click()
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)

    workbook_path = data_dir / "field_trial_data_v8_6_5.xlsx"
    windows = pd.read_excel(workbook_path, sheet_name="Windows", dtype=str)
    open_windows = windows[(windows["Trap ID"] == seeded["trap_id"]) & (windows["Status"] == "Open")]
    assert len(open_windows) == 1, "the trap must have exactly one open window after the inline repair"

    audit = pd.read_excel(workbook_path, sheet_name="Audit Log", dtype=str)
    trap_status_changes = audit[(audit["Record Type"] == "Trap") & (audit["Record ID"] == seeded["trap_id"]) & (audit["Field"] == "Status")]
    assert trap_status_changes.empty, (
        "the inline repair must not touch the trap's Status at all - "
        "no Deactivate/Activate round trip, since the trap was never actually pulled"
    )
