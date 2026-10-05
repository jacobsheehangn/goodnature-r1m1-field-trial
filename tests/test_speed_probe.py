"""Tests for FIELD_SPEED_PHASE1_BRIEF.md Part A - the speed probe.

Off unless SPEED_PROBE=1: no log lines, no caption, no change to what a
page renders. On: one SPEEDPROBE line per completed run (plus navigate /
rerun lines for aborted ones) in the server log and a one-line caption at
the bottom of every page, on a phone-sized and a desktop-sized viewport. A
forced exception inside the probe (test-only SPEED_PROBE_TEST_RAISE) must
leave the pages and every save working.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]

LOG_LINE = re.compile(
    r"^SPEEDPROBE page=(?P<page>\S*) kind=(?P<kind>complete|navigate|rerun) "
    r"run_ms=(?P<run_ms>\d+) load_ms=(?P<load_ms>\d+) save_ms=(?P<save_ms>\d+) "
    r"windows_rows=(?P<windows_rows>-?\d+) cb_ms=(?P<cb_ms>\d+) "
    r"checks_rows=(?P<checks_rows>-?\d+) followups_rows=(?P<followups_rows>-?\d+) "
    r"audit_rows=(?P<audit_rows>-?\d+) workbook_bytes=(?P<workbook_bytes>-?\d+)$"
)
CAPTION = re.compile(r"server [\d,]+ ms · tap→render (—|[\d,]+ ms) · median of \d+: (—|[\d,]+ ms) · load [\d,]+ ms · save [\d,]+ ms")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ProbeApp:
    def __init__(self, url: str, data_dir: Path, log_path: Path):
        self.url = url
        self.data_dir = data_dir
        self.log_path = log_path

    def log_lines(self) -> list[str]:
        if not self.log_path.exists():
            return []
        return [ln for ln in self.log_path.read_text(errors="replace").splitlines() if ln.startswith("SPEEDPROBE")]


def start_app(tmp_path: Path, extra_env: dict[str, str]):
    tmp_path.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    log_path = tmp_path / "server.log"
    env = os.environ.copy()
    env.pop("SPEED_PROBE", None)
    env.pop("SPEED_PROBE_TEST_RAISE", None)
    env.update(
        {
            "R1M1_ENVIRONMENT": "local",
            "R1M1_ALLOW_NO_AUTH": "true",
            "R1M1_SEED_MODE": "clean",
            "R1M1_DATA_DIR": str(data_dir),
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
            "PYTHONUNBUFFERED": "1",
            **extra_env,
        }
    )
    port = _free_port()
    log_file = open(log_path, "wb")
    process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.address", "127.0.0.1", "--server.port", str(port),
            "--server.headless", "true", "--browser.gatherUsageStats", "false",
        ],
        cwd=ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Local Streamlit process exited before becoming ready.")
        try:
            with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2) as response:
                if response.status == 200:
                    return process, log_file, ProbeApp(url, data_dir, log_path)
        except Exception:
            time.sleep(0.25)
    process.kill()
    raise RuntimeError("Local Streamlit app did not become ready within 60 seconds.")


def stop_app(process, log_file) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
    log_file.close()


@pytest.fixture
def probe_off(tmp_path: Path):
    process, log_file, app = start_app(tmp_path / "off", {})
    try:
        yield app
    finally:
        stop_app(process, log_file)


@pytest.fixture
def probe_on(tmp_path: Path):
    process, log_file, app = start_app(tmp_path / "on", {"SPEED_PROBE": "1"})
    try:
        yield app
    finally:
        stop_app(process, log_file)


@pytest.fixture
def probe_on_but_broken(tmp_path: Path):
    process, log_file, app = start_app(tmp_path / "broken", {"SPEED_PROBE": "1", "SPEED_PROBE_TEST_RAISE": "1"})
    try:
        yield app
    finally:
        stop_app(process, log_file)


def open_sites(page: Page, app: ProbeApp, viewport: dict | None = None) -> None:
    if viewport:
        page.set_viewport_size(viewport)
    page.goto(app.url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)


def caption_locator(page: Page):
    return page.frame_locator("iframe").last.locator("#r1m1-probe")


def expect_caption_really_visible(page: Page) -> None:
    """to_have_text passes for an element that is on the page but hidden, which
    is exactly how this caption shipped invisible once (the app's own CSS hides
    top-level helper iframes). Require it to be visible with a real size."""
    expect(caption_locator(page)).to_be_visible(timeout=15_000)
    box = caption_locator(page).bounding_box()
    assert box is not None and box["height"] >= 10 and box["width"] >= 100, f"caption has no real size: {box}"
    fits = caption_locator(page).evaluate("el => el.getBoundingClientRect().bottom <= window.innerHeight + 1")
    assert fits, "the caption text is taller than its frame, so part of it (e.g. 'save ... ms') is cut off"
    viewport = page.viewport_size
    assert box["x"] >= 0 and box["x"] + box["width"] <= viewport["width"] + 1, f"caption overflows the viewport: {box}"


def test_probe_off_emits_no_log_lines_and_no_caption(page: Page, probe_off: ProbeApp) -> None:
    open_sites(page, probe_off)
    page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
    page.get_by_role("link", name="Follow-ups", exact=True).click()
    expect(page.get_by_text("Follow-ups", exact=True).last).to_be_visible(timeout=30_000)
    page.wait_for_timeout(1_000)

    assert probe_off.log_lines() == []
    assert "tap→render" not in page.inner_text("body")
    for frame in page.frames:
        assert frame.query_selector("#r1m1-probe") is None


@pytest.mark.parametrize(
    "viewport",
    [{"width": 390, "height": 844}, {"width": 1440, "height": 1000}],
    ids=["phone", "desktop"],
)
def test_probe_on_logs_each_run_and_shows_the_caption(page: Page, probe_on: ProbeApp, viewport: dict) -> None:
    open_sites(page, probe_on, viewport)
    expect(caption_locator(page)).to_have_text(CAPTION, timeout=15_000)
    expect_caption_really_visible(page)

    page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
    expect(caption_locator(page)).to_have_text(CAPTION, timeout=15_000)
    expect_caption_really_visible(page)
    # A tap happened, so tap->render must now be a real number, not the
    # no-tap-yet dash.
    expect(caption_locator(page)).to_contain_text("tap→render ", timeout=10_000)
    expect(caption_locator(page)).not_to_contain_text("tap→render —", timeout=10_000)

    lines = probe_on.log_lines()
    assert lines, "expected SPEEDPROBE lines in the server log"
    parsed = [LOG_LINE.match(ln) for ln in lines]
    assert all(parsed), f"malformed probe lines: {[ln for ln, m in zip(lines, parsed) if not m]}"
    kinds = {m.group("kind") for m in parsed}
    assert "complete" in kinds
    assert any(m.group("page") == "sites" for m in parsed)
    assert any(m.group("page") == "visit" for m in parsed)
    windows_rows = {int(m.group("windows_rows")) for m in parsed if m.group("kind") == "complete"}
    assert windows_rows and min(windows_rows) > 0, "windows_rows must report the Windows sheet size"
    complete = [m for m in parsed if m.group("kind") == "complete"]
    assert all(int(m.group("workbook_bytes")) > 0 for m in complete), "workbook_bytes must report the file size"
    assert all(int(m.group("checks_rows")) >= 0 and int(m.group("followups_rows")) >= 0 and int(m.group("audit_rows")) >= 0 for m in complete)


def test_probe_median_tracks_up_to_ten_samples(page: Page, probe_on: ProbeApp) -> None:
    open_sites(page, probe_on)
    for _ in range(3):
        # A sample is recorded per tap once that tap's page has settled, so
        # leave a human-scale gap between taps (a tap landing before the
        # previous caption loaded is, by design, folded into the same sample).
        page.get_by_role("link", name="Follow-ups", exact=True).click()
        expect(page.get_by_text("Follow-ups", exact=True).last).to_be_visible(timeout=30_000)
        page.wait_for_timeout(1_500)
        page.get_by_role("link", name="Trap sites", exact=True).click()
        expect(page.get_by_text("Choose the trap site you are visiting today.", exact=True)).to_be_visible(timeout=30_000)
        page.wait_for_timeout(1_500)
    text = caption_locator(page).inner_text()
    median_n = int(re.search(r"median of (\d+)", text).group(1))
    assert median_n == 6


def test_a_failing_probe_leaves_pages_and_saves_working(page: Page, probe_on_but_broken: ProbeApp) -> None:
    app = probe_on_but_broken
    open_sites(page, app)
    page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Check", exact=True).first.click()
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)

    page.get_by_text("Trap still set, no animal", exact=True).click()
    expect(page.get_by_role("radio", name="Trap still set, no animal", exact=True)).to_be_checked(timeout=10_000)
    group = page.get_by_role("radiogroup", name="Trap relured, reset and ready?")
    yes = group.get_by_role("radio", name="Yes", exact=True)
    yes.focus()
    page.keyboard.press("Space")
    expect(yes).to_be_checked(timeout=10_000)
    save_button = page.get_by_role("button", name=re.compile(r"^Save check$"), exact=False)
    expect(save_button).to_be_enabled(timeout=10_000)
    save_button.click()
    expect(page.get_by_text("saved", exact=False).first).to_be_visible(timeout=30_000)

    checks = pd.read_excel(app.data_dir / "field_trial_data_v8_6_5.xlsx", sheet_name="Checks", dtype=str)
    assert len(checks) == 1, "the save must have gone through with the probe failing"
    assert "Traceback" not in page.inner_text("body")
    assert app.log_lines() == [], "a failing probe must not have produced partial output"


def _normalised_body(page: Page) -> str:
    # Streamlit keeps the previous page's elements (greyed) until the run
    # finishes, so let the page settle before reading it.
    page.wait_for_timeout(2_000)
    text = page.inner_text("body")
    text = re.sub(r"server [\d,]+ ms[^\n]*", "", text)
    text = re.sub(r"\d{1,2} \w{3} \d{4}", "<date>", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def test_probe_on_does_not_change_what_pages_render(page: Page, tmp_path: Path) -> None:
    results = {}
    for label, extra in [("off", {}), ("on", {"SPEED_PROBE": "1"})]:
        process, log_file, app = start_app(tmp_path / f"render_{label}", extra)
        try:
            open_sites(page, app)
            snapshots = {"sites": _normalised_body(page)}
            page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first.click()
            expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
            snapshots["visit"] = _normalised_body(page)
            page.get_by_role("button", name="Check", exact=True).first.click()
            expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)
            snapshots["check"] = _normalised_body(page)
            results[label] = snapshots
        finally:
            stop_app(process, log_file)
    for name in ("sites", "visit", "check"):
        assert results["on"][name] == results["off"][name], f"{name} page differs with the probe on"


@pytest.mark.parametrize("link", ["Follow-ups", "Trial performance"])
def test_caption_is_visible_on_the_other_top_level_pages(page: Page, probe_on: ProbeApp, link: str) -> None:
    open_sites(page, probe_on, {"width": 390, "height": 844})
    page.get_by_role("link", name=link, exact=True).click()
    expect(page.get_by_text(link, exact=True).last).to_be_visible(timeout=30_000)
    expect_caption_really_visible(page)
