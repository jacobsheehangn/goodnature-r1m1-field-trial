"""The golden record, through the real check page.

tests/test_check_save_golden.py holds app.build_check_records() to the frozen output of the old inline code. It cannot see the page
itself, which gathers the answers and hands them to that function. These tests answer the form in a browser for a spread of cells
(every finding, both carcass answers, both service answers, every kind of camera answer, a trap with a camera and one without) and
hold what Save check really wrote to the workbook to the frozen rows for the same cell, after replacing the IDs and times, which
differ run to run, with placeholders. If the page passed one answer to the wrong argument, one of these fails.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import check_save_matrix as m  # noqa: E402

WORKBOOK = "field_trial_data_v8_6_5.xlsx"

SEED = """
    import app, check_save_matrix as m
    with m.Pinned(app) as pin:
        pin.reset(0)
        app.save_data(m.build_fixture(app))
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def _serve(data_dir: Path):
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir),
               STREAMLIT_BROWSER_GATHER_USAGE_STATS="false", PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "tests")]))
    seeded = subprocess.run([sys.executable, "-c", textwrap.dedent(SEED)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
    assert seeded.returncode == 0, f"stdout={seeded.stdout}\nstderr={seeded.stderr[-3000:]}"
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.address", "127.0.0.1", "--server.port", str(port),
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    try:
        while True:
            if process.poll() is not None:
                raise RuntimeError("Local Streamlit process exited before becoming ready.")
            try:
                with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except Exception:
                if time.monotonic() > deadline:
                    raise RuntimeError("Local Streamlit app did not become ready within 60 seconds.")
                time.sleep(0.25)
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


# The cells driven through the page, picked from the golden matrix by their answers. None uploads photos (the photo chain has its own
# golden; the uploader is covered by the photo tests).
WANTED = [
    dict(profile="camera_trial", finding="Trap still set, no animal", service="Yes", camera="Yes", notes=""),
    dict(profile="camera_trial", finding="Trap fired, no animal", service="No", camera="Could not assess", notes=m.NOTE),
    dict(profile="camera_trial", finding="Trap disturbed", service="Yes", camera="No", issue="Offline", covers="Yes", adjusted=False),
    dict(profile="camera_trial", finding="Dead animal found", carcass="Yes", service="Yes", camera="Yes", photos=0, notes=""),
    dict(profile="camera_trial", finding="Dead animal found", carcass="No", service="No", camera="No", issue="Missing", covers="No", adjusted=True),
    dict(profile="camera_trial", finding="Trap missing"),
    dict(profile="camera_trial", finding="Unable to check"),
    dict(profile="nocamera_trial", finding="Trap still set, no animal", service="No"),
    dict(profile="nocamera_trial", finding="Dead animal found", carcass="Yes", service="Yes", photos=0, species="Rat", rat_type="Ship rat"),
    dict(profile="nocamera_trial", finding="Dead animal found", carcass="No", service="Yes", notes=m.NOTE),
]
GOLDEN_CELLS = m.cells()


def _pick(wanted: dict) -> dict:
    found = [c for c in GOLDEN_CELLS if all(c[k] == v for k, v in wanted.items())]
    assert found, f"no cell in the golden matrix matches {wanted}"
    return found[0]


UI_CELLS = [_pick(w) for w in WANTED]


def test_the_ui_cells_are_in_the_frozen_golden_and_the_frozen_code_agrees(tmp_path):
    """What the page is held to is the frozen inline code's output for the cell, and that is the golden: its digest is the stored one."""
    golden = {}
    for line in (ROOT / "tests" / "golden" / "check_save_golden_digests.tsv").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, value = line.rsplit("\t", 1)
            golden[key] = value
    keys = [m.cell_key(c) for c in UI_CELLS]
    assert len(set(keys)) == len(keys) and all(k in golden for k in keys)
    out = _frozen_rows(tmp_path, UI_CELLS)
    for key in keys:
        assert out[key]["digest"] == golden[key], f"the frozen inline code no longer gives the golden for {key}"


def _frozen_rows(tmp_path: Path, cells: list) -> dict:
    script = f"""
        import json, app, check_save_matrix as m
        cells = json.loads({json.dumps(json.dumps(cells))})
        out = {{}}
        with m.Pinned(app) as pin:
            pin.reset(0)
            base = m.build_fixture(app)
            for cell in cells:
                result = m.run_inline(app, pin, base, cell)
                out[m.cell_key(cell)] = {{"rows": result, "digest": m.digest(result)}}
        print(json.dumps(out))
    """
    data_dir = tmp_path / "frozen"
    data_dir.mkdir(exist_ok=True)
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir),
               PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "tests")]))
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"stdout={result.stdout[-1500:]}\nstderr={result.stderr[-3000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def frozen(tmp_path_factory):
    return _frozen_rows(tmp_path_factory.mktemp("frozen_ui"), UI_CELLS)


def _radio(page: Page, group: str, option: str) -> None:
    page.get_by_role("radiogroup", name=group).get_by_role("radio", name=option, exact=True).check(force=True)
    page.wait_for_timeout(500)


def _answer_the_form(page: Page, cell: dict) -> None:
    page.get_by_role("radio", name=cell["finding"], exact=True).check(force=True)
    page.wait_for_timeout(600)
    if cell["finding"] == "Dead animal found":
        _radio(page, "Carcass collected?", cell["carcass"])
        page.get_by_role("radio", name=cell["species"], exact=True).check(force=True)
        page.wait_for_timeout(400)
        if cell["rat_type"]:
            page.get_by_role("radio", name=cell["rat_type"], exact=True).check(force=True)
            page.wait_for_timeout(400)
        if cell["carcass"] == "Yes":
            page.get_by_role("radio", name=cell["condition"], exact=True).check(force=True)
            page.wait_for_timeout(300)
            page.get_by_role("checkbox", name=re.compile(r"Bag labelled")).evaluate("el => el.click()")
            page.wait_for_timeout(300)
    if cell["service"] in ("Yes", "No"):
        _radio(page, "Trap relured, reset and ready?", cell["service"])
        if cell["service"] == "No":
            page.get_by_label("Why is the trap not ready?").fill(cell["reason"])
            page.get_by_label("Why is the trap not ready?").press("Tab")
            page.wait_for_timeout(600)
    if PROFILE_HAS_CAMERA[cell["profile"]] and cell["finding"] not in m.NOT_ASSESSABLE:
        _radio(page, "Camera working and covering the trap?", cell["camera"])
        if cell["camera"] == "No":
            _radio(page, "Camera issue", cell["issue"])
            _radio(page, "Camera still covers the trap?", cell["covers"])
            if cell["adjusted"]:
                page.get_by_role("checkbox", name="Camera adjusted").evaluate("el => el.click()")
                page.wait_for_timeout(300)
    if cell["notes"]:
        page.get_by_label("Anything else to record?").fill(cell["notes"])
        page.get_by_label("Anything else to record?").press("Tab")
        page.wait_for_timeout(500)


PROFILE_HAS_CAMERA = {name: prof["camera"] for name, prof in m.PROFILES.items()}
ID = re.compile(r"(?:R1|M1)-[A-Z]+-\d+-W-[\w-]+|FU-[\w-]+|CHK-[\w-]+|VISIT-GOLDEN|V-[\w-]+")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}")


def _normalise(rows: dict, bag_ids: set, visit_ids: set) -> dict:
    """The rows with IDs numbered in order of first appearance and times replaced, so a run's rows compare with the frozen ones."""
    names, text = {}, json.dumps({k: rows[k] for k in ("checks_new", "windows", "followups_new")})
    for bag in bag_ids:  # a whole token only: "MAN-001" is also the end of the trap ID "R1-MAN-001"
        text = re.sub(rf"(?<![\w-]){re.escape(bag)}(?![\w-])", "<bag>", text)
    for visit in visit_ids:
        text = text.replace(visit, "<visit>")

    def label(match):
        found = match.group(0)
        if found not in names:
            names[found] = f"<id{len(names) + 1}>"
        return names[found]

    return json.loads(TIME.sub("<time>", ID.sub(label, text)))


def _read(data_dir: Path, sheet: str) -> pd.DataFrame:
    return pd.read_excel(data_dir / WORKBOOK, sheet_name=sheet, dtype=str).fillna("")


@pytest.mark.parametrize("cell", UI_CELLS, ids=[m.cell_key(c) for c in UI_CELLS])
def test_the_check_page_writes_the_frozen_rows(cell, frozen, tmp_path: Path, page: Page):
    page.set_viewport_size({"width": 414, "height": 896})
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _serve(data_dir) as url:
        before = {name: _read(data_dir, name) for name in ("Checks", "Windows", "Followups")}
        trap_id = m.PROFILES[cell["profile"]]["trap"]
        page.goto(url, wait_until="domcontentloaded")
        start = page.get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).first
        start.wait_for(timeout=45000)
        page.wait_for_timeout(1200)
        start.click()
        page.locator(f'[class*="visit_check_"][class*="_{trap_id}"] button').click()
        expect(page.get_by_text(trap_id).first).to_be_visible(timeout=20000)
        _answer_the_form(page, cell)
        page.get_by_role("button", name=re.compile(r"^Save check$")).click()
        expect(page.get_by_text(re.compile(r"Just saved"))).to_be_visible(timeout=40000)

        checks, windows, followups = (_read(data_dir, n) for n in ("Checks", "Windows", "Followups"))
        written = {
            "checks_new": checks.iloc[len(before["Checks"]):].values.tolist(),
            "windows": windows[windows["Trap ID"] == trap_id].values.tolist(),
            "followups_new": followups.iloc[len(before["Followups"]):].values.tolist(),
        }
        assert len(written["checks_new"]) == 1
        bags = {b for b in checks["Bag ID"].tolist() if b} | {m.BAG_ID}
        visits = set(checks["Visit ID"].tolist()) | {m.VISIT_ID}
        expected = _normalise(frozen[m.cell_key(cell)]["rows"], bags, visits)
        actual = _normalise(written, bags, visits)
        for part in ("checks_new", "windows", "followups_new"):
            assert actual[part] == expected[part], f"{part} differ for {m.cell_key(cell)}"
