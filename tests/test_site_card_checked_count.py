"""Regression test for a field-reported bug (2026-08-14 field notes):

The Trap sites list card showed "10 of 9 traps checked" for a 9-trap site -
a numerically impossible count - while the site's own detail page correctly
showed "8 of 9 traps checked" for the same in-progress visit.

Root cause: the list card counted raw Check rows for the visit
(`len(checks)`), while the site-detail page's progress bar already deduped
by unique Trap ID (`len(set(checks["Trap ID"]))`). A trap checked twice in
one visit - plausible after the resume-prompt bug in
test_resume_already_checked_trap.py led an operator to re-check a trap they
'd already done - inflated the list card's raw count past the real trap
total, while the detail page (correctly) stayed capped.

This seeds a genuine duplicate Check row directly (bypassing the UI, since
the resume-prompt bug that produced one in the field is fixed and tested
separately) to test the display fix in isolation.
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
def site_with_duplicate_check_app(tmp_path: Path):
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
        from datetime import timedelta

        data = app.create_sample_data()
        site = data["Sites"].iloc[0]
        site_id = site["Site ID"]
        traps = data["Traps"][(data["Traps"]["Site ID"] == site_id) & (data["Traps"]["Status"] == "Active")]
        trap_count = len(traps)
        assert trap_count >= 3, "need at least 3 active traps at the first site for this test to mean anything"
        first_two = traps["Trap ID"].tolist()[:2]

        visit_id = "TEST-DUP-VISIT-1"
        vrow = {c: "" for c in app.SHEETS["Visits"]}
        vrow.update({
            "Visit ID": visit_id, "Site ID": site_id, "Status": "In progress",
            "Start Time": app.dtstr(app.now() - timedelta(hours=1)), "Operator": "Test",
        })
        data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([vrow])], ignore_index=True)

        # Trap A gets checked twice (the field-reported duplicate); Trap B once.
        rows = []
        for i, trap_id in enumerate([first_two[0], first_two[0], first_two[1]]):
            row = {c: "" for c in app.SHEETS["Checks"]}
            row.update({
                "Check ID": f"TEST-DUP-CHECK-{i}", "Visit ID": visit_id, "Trap ID": trap_id,
                "Check Time": app.dtstr(app.now() - timedelta(minutes=30 - i)),
                "Finding": "Trap still set, no animal",
            })
            rows.append(row)
        data["Checks"] = pd.concat([data["Checks"], pd.DataFrame(rows)], ignore_index=True)
        app.save_data(data)
        print(json.dumps({
            "site_name": site["Site Name"], "trap_count": trap_count, "unique_checked": 2,
        }))
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


def test_list_card_checked_count_is_deduped_not_a_raw_row_count(
    page: Page, site_with_duplicate_check_app
) -> None:
    base_url, seeded = site_with_duplicate_check_app
    trap_count = seeded["trap_count"]
    unique_checked = seeded["unique_checked"]

    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    # The card's meta line combines this with "· Every N days" in one
    # element (e.g. "2 of 6 traps checked · Every 3 days"), so this can only
    # be a substring match, not exact.
    expected_text = f"{unique_checked} of {trap_count} traps checked"
    expect(page.get_by_text(expected_text, exact=False)).to_be_visible(timeout=15_000)

    impossible_text = f"{trap_count + 1} of {trap_count} traps checked"
    assert page.get_by_text(impossible_text, exact=False).count() == 0, (
        "the checked count must never exceed the trap count, however many duplicate Check rows exist"
    )
