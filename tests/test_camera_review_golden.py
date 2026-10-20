"""Batch 1: what a Camera review save writes, frozen from main before the save logic was moved into app.apply_camera_review().

tests/golden/camera_review_golden.json holds, for every reachable answer set (124: kill and other reviews, evidence usable or not, every target,
interaction level, strike and activation answer, every video assessment, with and without notes and a link), the Windows row and the Follow-up row
the old inline block wrote. It was made by running the frozen block (golden/camera_review_inline_block_main.txt), never the new function. Never edited
to make a test pass."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "camera_review_golden.json"
sys.path.insert(0, str(ROOT / "tests"))
import camera_review_matrix as m  # noqa: E402


def _run(tmp_path: Path, script: str) -> dict:
    data_dir = tmp_path / "data"; data_dir.mkdir(exist_ok=True)
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir),
               PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "tests")]))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, f"stdout={r.stdout[-1500:]}\nstderr={r.stderr[-3000:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> dict:
    return _run(tmp_path_factory.mktemp("cr"), """
        import json, app, camera_review_matrix as m
        print(json.dumps({r: m.compute(app, r, keep_rows=lambda c: True)["rows"] for r in ("extracted", "inline")}))
    """)


def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["cells"]


def test_the_matrix_is_whole_and_cannot_shrink_quietly():
    cells = m.cells()
    golden = _golden()
    assert {m.cell_key(c) for c in cells} == set(golden) and len(golden) == len(cells) == 124
    assert {c["target"] for c in cells if not c["is_kill"] and c["usable"] == "Yes"} == {"Yes", "No", "Unclear"}
    assert {c["assessment"] for c in cells if c["is_kill"] and c["usable"] == "Yes"} == set(m.ASSESSMENTS)
    assert {c["interaction_level"] for c in cells if c["target"] == "Yes"} == set(m.LEVELS)
    assert {(c["strike_area"], c["activated"]) for c in cells if c["target"] == "Yes" and not c["is_kill"]} == {
        ("Yes", "Yes"), ("Yes", "No"), ("Yes", "Unclear"), ("No", "No"), ("Unclear", "Unclear")}


def test_the_function_the_page_calls_writes_exactly_what_the_old_inline_block_wrote(runs):
    golden = _golden()
    bad = [k for k in golden if runs["extracted"][k] != golden[k]["rows"]]
    assert not bad, f"{len(bad)} cells differ, first: {bad[:5]}"


def test_the_frozen_inline_block_still_reproduces_the_golden(runs):
    golden = _golden()
    bad = [k for k in golden if runs["inline"][k] != golden[k]["rows"]]
    assert not bad, f"{len(bad)} cells differ, first: {bad[:5]}"


def test_a_change_in_the_classification_is_noticed(tmp_path):
    out = _run(tmp_path, """
        import json, app, camera_review_matrix as m
        real = app.classify_camera_outcome
        app.classify_camera_outcome = lambda *a, **k: "Activated, no kill" if real(*a, **k) == "Entered, no activation" else real(*a, **k)
        print(json.dumps(m.compute(app, "extracted")["digests"]))
    """)
    golden = _golden()
    moved = {k for k in golden if out[k] != golden[k]["digest"]}
    assert moved and all("strike=Yes | activated=No" in k for k in moved)
