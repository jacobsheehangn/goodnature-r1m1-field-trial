"""Regression test for a 2026-09-16 field report:

A follow-up task's "Build" context field was reading the trap's *current*
Build Version (a live lookup), not what the trap was actually running when
the linked window was open. Once a trap's build gets reassigned (e.g. for a
new trial), every one of its older, still-open follow-ups started showing
the new build against an evidence period that predates it even existing -
in the field report, "Build: 18" on a task whose evidence period was weeks
before Build 18 was ever added to the app.

Confirmed this never touched Trial Performance/Kills reporting - that reads
Windows["Build Version"] directly, which is set once when a window opens
and never changes afterward. This was a display-only bug isolated to the
follow-up detail screen, which did a live trap lookup instead of using that
same already-correct historical value from the linked window.
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
def reassigned_build_app(tmp_path: Path):
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
    seed = """
        import json, app, pandas as pd
        data = app.create_sample_data()
        trap = data["Traps"][data["Traps"]["Trap ID"] == "M1-MAN-004"].iloc[0]
        trap_id = trap["Trap ID"]

        # A closed window while the trap was on its ORIGINAL build, with an
        # open Camera review follow-up still attached to it.
        window_id = "TEST-HIST-BUILD-W1"
        wrow = {c: "" for c in app.SHEETS["Windows"]}
        wrow.update({
            "Window ID": window_id, "Trap ID": trap_id, "Product": trap["Product"],
            "Build Version": "R1 Build ORIGINAL", "Site ID": trap["Site ID"],
            "Camera Assigned": "Yes", "Status": "Closed",
            "Start Time": "2026-08-24 13:15:00", "End Time": "2026-08-31 18:50:00",
            "Finding At Close": "Trap still set, no animal", "Review Status": "Open",
        })
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([wrow])], ignore_index=True)

        followup_id = "TEST-HIST-BUILD-FU1"
        frow = [followup_id, "Camera review", trap["Site ID"], trap_id, "", window_id, "",
                "2026-08-31 18:50:00", "Normal", "Trap still set, no animal",
                "Confirm target interaction, activation, kill and video evidence", "Open", "", ""]
        data["Followups"] = pd.concat([data["Followups"], pd.DataFrame([frow], columns=app.SHEETS["Followups"])], ignore_index=True)

        # The trap's CURRENT build has since moved on - this is the live
        # value the bug incorrectly showed instead of the window's own.
        idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
        data["Traps"].at[idx, "Build Version"] = "R1 Build REASSIGNED"

        app.save_data(data)
        print(json.dumps({"trap_id": trap_id, "followup_id": followup_id}))
    """
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(seed)],
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
        yield url, seeded
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_followup_detail_shows_the_windows_own_build_not_the_traps_current_one(
    page: Page, reassigned_build_app
) -> None:
    base_url, seeded = reassigned_build_app
    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("link", name="Follow-ups", exact=True).click()
    expect(page.get_by_text("Follow-ups", exact=True).last).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Review", exact=True).first.click()
    expect(page.get_by_text("Task context", exact=True)).to_be_visible(timeout=15_000)

    expect(page.get_by_text("Build: R1 Build ORIGINAL", exact=False)).to_be_visible(timeout=10_000)
    expect(page.get_by_text("Build: R1 Build REASSIGNED", exact=False)).not_to_be_visible()
