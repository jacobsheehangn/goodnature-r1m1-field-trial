"""Regression test for the sign-out access-token leak found in the 2026-08-13 UX audit.

require_authentication() restores a session from a signed token in the URL query
string (?access=...) so a refresh survives without re-prompting - a deliberate fix
for field connectivity. Sign out has to clear that token too, or a rerun right
after signing out silently re-authenticates from the still-valid URL. This uses a
dedicated fixture (real password, no R1M1_ALLOW_NO_AUTH) rather than the shared
`local_app` fixture, which bypasses login entirely.
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
TEST_PASSWORD = "audit-regression-test-pw"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def password_app(tmp_path: Path):
    """Launch a local app that actually requires the shared password to sign in."""
    port = _free_port()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    env = os.environ.copy()
    env.update(
        {
            "R1M1_ENVIRONMENT": "local",
            "R1M1_ALLOW_NO_AUTH": "false",
            "R1M1_APP_PASSWORD": TEST_PASSWORD,
            "R1M1_SEED_MODE": "clean",
            "R1M1_DATA_DIR": str(data_dir),
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        }
    )

    process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.address", "127.0.0.1",
            "--server.port", str(port),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
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


def _sign_in(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    page.locator('input[type="password"][aria-label="Password"]').first.fill(TEST_PASSWORD)
    page.get_by_role("button", name=re.compile(r"^sign in$", re.I)).click()
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)


def test_sign_out_clears_the_url_access_token(page: Page, password_app: str) -> None:
    _sign_in(page, password_app)
    assert "access=" in page.url, "expected a signed access token in the URL after signing in"

    page.get_by_role("button", name="Administration", exact=False).click()
    page.get_by_role("button", name="Sign out", exact=True).click()

    expect(page.locator('input[type="password"][aria-label="Password"]').first).to_be_visible(timeout=30_000)
    assert "access=" not in page.url, "sign out must clear the URL access token, not just session state"


def test_reload_after_sign_out_does_not_silently_reauthenticate(page: Page, password_app: str) -> None:
    _sign_in(page, password_app)

    page.get_by_role("button", name="Administration", exact=False).click()
    page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page.locator('input[type="password"][aria-label="Password"]').first).to_be_visible(timeout=30_000)

    # Reloading (simulating the URL having been bookmarked/shared/left open) must
    # still show the login page - the bug this regression-tests let a stale URL
    # silently re-authenticate here instead.
    page.reload(wait_until="domcontentloaded")
    expect(page.locator('input[type="password"][aria-label="Password"]').first).to_be_visible(timeout=30_000)
    assert page.get_by_text("Trap sites", exact=True).count() == 0
