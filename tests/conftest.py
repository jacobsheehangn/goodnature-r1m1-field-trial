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
EVIDENCE = ROOT / "evidence"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def local_app(tmp_path: Path, request):
    """Launch a fresh app and retain its resulting workbook as release evidence."""
    port = _free_port()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env = os.environ.copy()
    env.update({
        "R1M1_ENVIRONMENT": "local",
        "R1M1_ALLOW_NO_AUTH": "true",
        "R1M1_SEED_MODE": "clean",
        "R1M1_DATA_DIR": str(data_dir),
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    })
    log_path = EVIDENCE / "streamlit.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.address", "127.0.0.1",
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 90
    try:
        import urllib.request
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Local Streamlit process exited before becoming ready. See evidence/streamlit.log")
            try:
                with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("Local Streamlit app did not become ready within 90 seconds")
        yield {"url": url, "data_dir": data_dir}
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
        target = EVIDENCE / "workbooks" / request.node.name
        target.mkdir(parents=True, exist_ok=True)
        for path in data_dir.glob("*.xlsx"):
            shutil.copy2(path, target / path.name)


@pytest.fixture
def page(request):
    EVIDENCE.mkdir(exist_ok=True)
    videos = EVIDENCE / "videos"
    traces = EVIDENCE / "traces"
    videos.mkdir(parents=True, exist_ok=True)
    traces.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(record_video_dir=str(videos), record_video_size={"width": 430, "height": 932})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        try:
            yield page
        finally:
            trace_path = traces / f"{request.node.name}.zip"
            context.tracing.stop(path=str(trace_path))
            context.close()
            browser.close()
