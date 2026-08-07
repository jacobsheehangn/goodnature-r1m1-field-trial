from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def local_app(tmp_path: Path):
    """Launch a fresh local app with isolated clean data for every browser test."""
    port = _free_port()
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

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
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


@pytest.fixture
def page():
    with sync_playwright() as p:
        try:
            launch_kwargs = {"headless": True}
            if Path("/usr/bin/chromium").exists():
                launch_kwargs["executable_path"] = "/usr/bin/chromium"
            browser = p.chromium.launch(**launch_kwargs)
        except Exception as exc:
            pytest.fail(
                "Chromium is not installed. Run `playwright install chromium`. " + str(exc),
                pytrace=False,
            )
        context = browser.new_context()
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()
