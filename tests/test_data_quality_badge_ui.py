"""Phase S (TRIAL_LIFECYCLE_BRIEF.md): the Administration menu's Data quality
badge now comes from a count cached on the workbook's modified time. This
drives the real app to prove the badge still shows the right number and
updates after a save (which changes the modified time), rather than going
stale."""
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
def two_flagged_checks_app(tmp_path: Path):
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
    # Two checks at different sites, a day apart: each is isolated, so each is
    # a Data quality candidate.
    seed = """
        import app, pandas as pd
        data = app.create_sample_data()
        site_a = data["Traps"].iloc[0]
        site_b = data["Traps"][data["Traps"]["Site ID"] != site_a["Site ID"]].iloc[0]
        rows = []
        for check_id, trap, when in [("CHK-DQ-1", site_a, "2026-09-01 08:00:00"), ("CHK-DQ-2", site_b, "2026-09-02 08:00:00")]:
            row = {c: "" for c in app.SHEETS["Checks"]}
            row.update({"Check ID": check_id, "Visit ID": "VIS-DQ", "Trap ID": trap["Trap ID"], "Check Time": when, "Finding": "Trap still set, no animal"})
            rows.append(row)
        data["Checks"] = pd.DataFrame(rows, columns=app.SHEETS["Checks"])
        app.save_data(data)
    """
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(seed)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    port = _free_port()
    env2 = env.copy()
    env2["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.address", "127.0.0.1", "--server.port", str(port),
            "--server.headless", "true", "--browser.gatherUsageStats", "false",
        ],
        cwd=ROOT, env=env2, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    import urllib.request

    deadline = time.monotonic() + 60
    ready = False
    try:
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
        assert ready, "Local Streamlit app did not become ready."
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _badge_text(page: Page) -> str:
    """The badge is a CSS ::after on the Data quality menu link, so read it
    from the computed style. Opens the Administration menu first."""
    page.get_by_role("button", name="Administration", exact=False).click()
    link = page.locator('a[data-testid="stPageLink-NavLink"][href*="data-quality"]').first
    expect(link).to_be_visible(timeout=15_000)
    content = link.evaluate("el => getComputedStyle(el, '::after').content")
    return content.strip('"')


def test_badge_shows_the_count_and_updates_after_a_save(page: Page, two_flagged_checks_app: str) -> None:
    page.goto(two_flagged_checks_app, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)

    assert _badge_text(page) == "2", "two isolated checks should show a badge of 2"

    page.locator('a[data-testid="stPageLink-NavLink"][href*="data-quality"]').first.click()
    expect(page.get_by_text("2 checks flagged for review", exact=False)).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Review", exact=True).first.click()
    expect(page.get_by_text("Reviewing candidate 1 of 2", exact=False)).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Confirm as real", exact=True).click()
    expect(page.get_by_text("Confirmed as real.", exact=True)).to_be_visible(timeout=30_000)

    # That confirm saved the workbook, so the cached count must be recomputed.
    page.wait_for_timeout(500)
    assert _badge_text(page) == "1", "the badge went stale after a save"
