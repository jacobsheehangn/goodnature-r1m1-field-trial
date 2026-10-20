"""The server stack is pinned to what the tests run on (20 Oct 2026).

Streamlit 1.60.0 serves through Starlette but only requires `starlette>=0.40,<2`, so Render's fresh build installed the newest one, 1.9.0, whose gzip
handling breaks Streamlit's own gzip middleware for binary responses: the sign-in logo (an image) and the Lato fonts came back HTTP 500 on the live app
while every text file was fine. `requirements.txt` now pins Starlette to the version the suite runs on; these tests fail if the two ever differ, and if
a binary file is not served."""
from __future__ import annotations

import gzip
import re
import sys
import urllib.error
import urllib.request
from importlib import metadata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_check_save_golden_ui import _serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FONT = "/app/static/fonts/lato-400-latin.woff2"
ICON = "/app/static/icons/lock.svg"


def pins() -> dict:
    found = {}
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        match = re.match(r"^\s*([A-Za-z0-9_.-]+)==([^\s#]+)", line)
        if match:
            found[match.group(1).lower()] = match.group(2)
    return found


def test_requirements_pin_streamlit_and_starlette_to_the_versions_the_tests_run_on() -> None:
    found = pins()
    for name in ("streamlit", "starlette"):
        assert name in found, f"{name} must be pinned with == in requirements.txt (an unpinned server stack drifted on Render, 20 Oct 2026)"
        assert metadata.version(name) == found[name], f"{name}: the tests run on {metadata.version(name)} but requirements.txt pins {found[name]}"


def get(url: str, path: str) -> tuple:
    """GET as a browser does (gzip accepted): (status, content-type, first bytes)."""
    request = urllib.request.Request(url + path, headers={"Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return response.status, response.headers.get("Content-Type", ""), body[:4]
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), b""


def check_binary_and_text_files_are_served(url: str) -> None:
    status, kind, head = get(url, FONT)
    assert status == 200 and head == b"wOF2", f"a font (binary) must be served: {status} {kind}"
    status, kind, _ = get(url, ICON)
    assert status == 200 and kind.startswith("image/svg"), f"an icon (text) must be served: {status} {kind}"


def test_a_binary_file_and_a_text_file_are_served_to_a_browser_that_accepts_gzip(tmp_path: Path) -> None:
    with _serve(tmp_path / "d") as url:
        check_binary_and_text_files_are_served(url)
