"""The golden record for Save check (Phase 6, S3).

What Save check writes to Checks, Windows and Follow-ups, for every outcome x carcass x service x camera x trap combination, was frozen
from the check page's inline code on main (20a454a) before that code was moved into app.build_check_records(). These tests hold the
function the page calls to that frozen output, byte for byte, and hold the frozen inline code to it too (so the golden is provably
today's behaviour, not whatever the new code does). The photo chain (staging, finalising, Photos rows, files) is held to its own golden.

The golden is never edited to make a test pass. A deliberate behaviour change replaces it with
`tests/golden/freeze_check_save.py --deliberate "<why>"`, in a reviewed change that lists the cells that moved.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"
sys.path.insert(0, str(ROOT / "tests"))
import check_save_matrix as m  # noqa: E402  (pure data helpers; the app is only imported in the subprocess)


def _run(tmp_path: Path, script: str, timeout: int = 600) -> dict:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir),
               PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "tests")]))
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, f"stdout={result.stdout[-2000:]}\nstderr={result.stderr[-3000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def _golden_digests() -> dict:
    """The golden frozen from main, as it was frozen."""
    out = {}
    for line in (GOLDEN / "check_save_golden_digests.tsv").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, value = line.rsplit("\t", 1)
            out[key] = value
    return out


def _changes() -> dict:
    """The deliberate changes laid over the frozen golden (check_save_golden_changes.json), each with a reason."""
    path = GOLDEN / "check_save_golden_changes.json"
    return json.loads(path.read_text(encoding="utf-8"))["cells"] if path.exists() else {}


def _current_golden_digests() -> dict:
    return {**_golden_digests(), **{key: change["digest"] for key, change in _changes().items()}}


def _diff(expected: dict, actual: dict, limit: int = 12) -> str:
    moved = [k for k in expected if expected[k] != actual.get(k)]
    missing = [k for k in expected if k not in actual]
    extra = [k for k in actual if k not in expected]
    return f"{len(moved)} cells differ, {len(missing)} missing, {len(extra)} unexpected. First: " + "; ".join((moved + missing + extra)[:limit])


@pytest.fixture(scope="module")
def matrix_runs(tmp_path_factory) -> dict:
    """Both runners over the whole matrix, once, in a process that has imported the app."""
    tmp = tmp_path_factory.mktemp("golden")
    return _run(tmp, """
        import json, app, check_save_matrix as m
        out = {}
        for runner in ("extracted", "inline"):
            r = m.compute(app, runner, keep_rows_for=m.is_representative)
            out[runner] = {"digests": r["digests"], "rows": r["rows"], "touched_something_else": r["touched_something_else"]}
        print(json.dumps(out))
    """)


def test_the_function_the_page_calls_reproduces_the_golden_for_the_whole_matrix(matrix_runs):
    expected = _current_golden_digests()
    actual = matrix_runs["extracted"]["digests"]
    assert actual == expected, _diff(expected, actual)


def test_the_frozen_inline_code_still_reproduces_the_golden(matrix_runs):
    """The proof that the golden is the old behaviour: the old code, run again, gives the same rows."""
    expected = _golden_digests()
    actual = matrix_runs["inline"]["digests"]
    assert actual == expected, _diff(expected, actual)


def test_the_readable_rows_match_in_full(matrix_runs):
    frozen = json.loads((GOLDEN / "check_save_golden_rows.json").read_text(encoding="utf-8"))["cells"]
    frozen.update({key: change["rows"] for key, change in _changes().items() if key in frozen})
    actual = matrix_runs["extracted"]["rows"]
    assert set(actual) == set(frozen)
    for key, rows in frozen.items():
        assert actual[key] == rows, f"rows differ for: {key}"


def test_nothing_but_the_trap_checks_and_follow_ups_is_written(matrix_runs):
    for runner in ("extracted", "inline"):
        assert matrix_runs[runner]["touched_something_else"] == [], f"{runner}: another trap's window or another sheet changed"


def test_the_matrix_covers_every_dimension_and_cannot_shrink_quietly():
    cells = m.cells()
    golden = _current_golden_digests()
    assert {m.cell_key(c) for c in cells} == set(golden), "the matrix and the frozen golden list different cells"
    assert len(golden) == len(cells) >= 2700
    assert {c["finding"] for c in cells} == set(m.FINDINGS)
    assert {c["profile"] for c in cells} == set(m.PROFILES)
    assert {c["carcass"] for c in cells if c["finding"] == "Dead animal found"} == {"Yes", "No"}
    assert {c["photos"] for c in cells if c["finding"] == "Dead animal found" and c["carcass"] == "Yes"} == {0, 1, 3}
    assert {c["service"] for c in cells} == {"Yes", "No", "NA"}
    assert {(c["issue"], c["covers"], c["adjusted"]) for c in cells if c["camera"] == "No"} == {
        (i, cv, a) for i in m.CAMERA_ISSUES for cv in m.COVERS for a in (False, True)
    }
    assert {c["camera"] for c in cells} == {"NA", "Yes", "Could not assess", "No"}
    assert {(c["species"], c["rat_type"]) for c in cells if c["species"]} == set(m.SPECIES_RAT)
    assert {c["condition"] for c in cells if c["condition"]} == set(m.CONDITIONS)
    assert {c["notes"] for c in cells} == {"", m.NOTE}
    # every camera-trap cell for the two findings the camera check does not apply to is in it (the S4 cells)
    s4 = [c for c in cells if c["profile"].startswith("camera") and c["finding"] in m.NOT_ASSESSABLE]
    assert len(s4) == 2 * 2 * 2


def test_the_photo_chain_matches_its_golden(tmp_path):
    frozen = json.loads((GOLDEN / "check_save_golden_photos.json").read_text(encoding="utf-8"))["cases"]
    out = _run(tmp_path, """
        import json, app, check_save_matrix as m
        print(json.dumps({r: m.compute_photo_chain(app, r) for r in ("extracted", "inline")}))
    """)
    assert out["inline"] == frozen, "the frozen inline code no longer reproduces the photo-chain golden"
    assert out["extracted"] == frozen, "the extracted function no longer reproduces the photo-chain golden"
    assert [len(frozen[c]["photos"]) for c in m.PHOTO_CASES] == [0, 1, 3, 1, 3, 0, 0]


def test_the_golden_notices_a_change_in_behaviour(tmp_path):
    """Negative controls: break the camera-issue rule, then the priority of a follow-up; the golden must see each, in exactly the cells
    where it matters, and in nothing else."""
    expected = _current_golden_digests()
    out = _run(tmp_path, """
        import json, app, check_save_matrix as m
        real_required, real_add = app.camera_issue_required, app.add_followup
        app.camera_issue_required = lambda *a, **k: False
        no_issue = m.compute(app, "extracted")["digests"]
        app.camera_issue_required = real_required
        def add(data, followup_type, site, trap, visit, window, bag, reason, required, priority):
            return real_add(data, followup_type, site, trap, visit, window, bag, reason, required, "Normal" if followup_type == "Trap not ready" else priority)
        app.add_followup = add
        normal_priority = m.compute(app, "extracted")["digests"]
        cells = {m.cell_key(c): c for c in m.cells()}
        print(json.dumps({"no_issue": no_issue, "normal_priority": normal_priority}))
    """)
    cells = {m.cell_key(c): c for c in m.cells()}
    moved_issue = {k for k in expected if out["no_issue"][k] != expected[k]}
    wanted_issue = {k for k, c in cells.items() if m.camera_issue_required_for(c) and c["finding"] not in m.NOT_ASSESSABLE}
    assert moved_issue == wanted_issue and moved_issue
    moved_priority = {k for k in expected if out["normal_priority"][k] != expected[k]}
    assert moved_priority == {k for k, c in cells.items() if c["finding"] not in m.NOT_ASSESSABLE and c["service"] == "No"}


# ---------------------------------------------------------------- S4: the camera of a trap that was not assessed
S4_REASON_WORDS = "Not assessed"


def _s4_cells() -> set:
    """The only cells the S4 fix may move: a trap with a camera, a finding that means the trap was not assessed."""
    return {m.cell_key(c) for c in m.cells() if m.PROFILES[c["profile"]]["camera"] and c["finding"] in m.NOT_ASSESSABLE}


def test_the_deliberate_changes_are_exactly_the_s4_cells_and_nothing_else():
    changes = _changes()
    assert set(changes) == _s4_cells() and len(changes) == 8
    base = _golden_digests()
    assert all(change["digest"] != base[key] for key, change in changes.items()), "a recorded change that is not a change"


def test_s4_changes_only_the_camera_columns_and_the_camera_issue_task():
    """Read against the frozen rows: the new rows equal the old ones except Camera Condition, Camera Covers Trap and the missing
    Camera issue follow-up."""
    frozen = json.loads((GOLDEN / "check_save_golden_rows.json").read_text(encoding="utf-8"))["cells"]
    camera_condition, camera_covers = m_columns()
    readable = [key for key in _changes() if key in frozen]  # the cells with notes have a digest, not stored rows
    assert len(readable) == 4
    for key in readable:
        old, new = frozen[key], _changes()[key]["rows"]
        assert old["checks_new"][0][camera_condition] == "No camera" and old["checks_new"][0][camera_covers] == "Not applicable"
        assert new["checks_new"][0][camera_condition] == S4_REASON_WORDS and new["checks_new"][0][camera_covers] == S4_REASON_WORDS
        patched = list(old["checks_new"][0])
        patched[camera_condition], patched[camera_covers] = S4_REASON_WORDS, S4_REASON_WORDS
        assert new["checks_new"][0] == patched, f"{key}: something besides the two camera columns changed in the Checks row"
        assert new["windows"] == old["windows"], f"{key}: a window changed"
        assert [f for f in old["followups_new"] if f[1] != "Camera issue"] == new["followups_new"]
        assert [f[1] for f in old["followups_new"] if f[1] == "Camera issue"] == ["Camera issue"], f"{key}: the old code raised one Camera issue"
        assert not [f for f in new["followups_new"] if f[1] == "Camera issue"], f"{key}: still raises a Camera issue"


def test_a_trap_without_a_camera_is_unchanged_and_an_assessed_camera_still_raises_its_issue():
    frozen = json.loads((GOLDEN / "check_save_golden_rows.json").read_text(encoding="utf-8"))["cells"]
    for key, rows in frozen.items():
        if key in _changes():
            continue
        row = rows["checks_new"][0]
        camera_condition, camera_covers = m_columns()
        if key.startswith("nocamera") and any(f in key for f in m.NOT_ASSESSABLE):
            assert (row[camera_condition], row[camera_covers]) == ("No camera", "Not applicable"), key
        if key.startswith("camera") and "camera=No" in key and not any(f in key for f in m.NOT_ASSESSABLE):
            assert [f for f in rows["followups_new"] if f[1] == "Camera issue"], f"{key}: an assessed, failing camera lost its Camera issue"


def m_columns() -> tuple:
    columns = [
        "Check ID", "Visit ID", "Trap ID", "Window Closed", "Check Time", "Finding", "Species", "Rat Type", "Animal Condition When Found", "Bag ID",
        "Animal Cleared", "Animal Bagged", "Lure Condition", "Relured", "Reset Required", "Trap Reset", "Trap Ready After Check", "Trap Function",
        "Site Condition", "Camera Condition", "Camera Covers Trap", "Camera Adjusted", "New Window", "Notes", "Excluded", "Exclusion Reason",
    ]
    return columns.index("Camera Condition"), columns.index("Camera Covers Trap")
