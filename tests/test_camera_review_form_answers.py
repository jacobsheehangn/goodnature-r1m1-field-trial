"""Batch 1: the new Camera review form hands apply_camera_review the same answers the old form did, for every reachable answer set.

tests/camera_review_matrix.py holds every answer set the old page let through its own validation (the cells behind the golden record of what a Camera review
writes). Here each cell is turned back into what the new form holds when it is answered that way, and the form's two pure steps are held to it:
camera_review_errors() finds nothing missing (the cell is reachable), and camera_review_saved_answers() gives exactly the answers the cell passes on. Together with
test_camera_review_golden.py (the same answers write the same rows) this is the proof that moving the form to option rows and segmented controls changed nothing
that is saved. A last test shows each required answer, taken away, is asked for and nothing else."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = """
    import json
    import app, camera_review_matrix as cm
    def form_answers(c):
        yes = c["usable"] == "Yes"
        non_kill_target_yes = yes and not c["is_kill"] and c["target"] == "Yes"
        a = dict(
            is_kill_review=c["is_kill"], usable=c["usable"],
            target=(c["target"] if (yes and not c["is_kill"]) else None),
            level=(c["interaction_level"] if (yes and (c["is_kill"] or c["target"] == "Yes")) else None),
            strike=(c["strike_area"] if non_kill_target_yes else None),
            activated=(c["activated"] if (non_kill_target_yes and c["strike_area"] == "Yes") else None),
            assessment=(c["assessment"] if (yes and c["is_kill"]) else None),
            first_d=cm.FIRST.date() if c["first"] else None, first_t=cm.FIRST.time() if c["first"] else None,
            trigger_d=cm.TRIGGER.date() if c["trigger"] else None, trigger_t=cm.TRIGGER.time() if c["trigger"] else None,
            kill_d=cm.KILL.date() if c["kill"] else None, kill_t=cm.KILL.time() if c["kill"] else None,
            window_start=cm.T0, window_end=cm.WINDOW_END)
        return a
    results = []
    for c in cm.cells():
        a = form_answers(c)
        errors = app.camera_review_errors(**a)
        saved = app.camera_review_saved_answers(**{k: a[k] for k in ("is_kill_review", "usable", "target", "level", "strike", "activated", "assessment")})
        want = {"target": c["target"], "interaction_level": c["interaction_level"], "strike_area": c["strike_area"], "activated": c["activated"], "assessment": c["assessment"]}
        # Taking one required answer away must ask for exactly that answer (nothing else, and not nothing).
        gone = []
        for name in ("target", "level", "strike", "activated", "assessment"):
            if a[name] is not None and a["usable"] == "Yes":
                b = dict(a); b[name] = None
                gone.append([name, [f for f, _ in app.camera_review_errors(**b)]])
        for pair, key in (("first", "first"), ("trigger", "trigger"), ("kill", "kill")):
            if a[pair + "_d"] is not None:
                b = dict(a); b[pair + "_t"] = None
                gone.append([pair, [f for f, _ in app.camera_review_errors(**b)]])
        results.append({"key": cm.cell_key(c), "errors": [list(e) for e in errors], "saved": saved, "want": want, "gone": gone})
    print(json.dumps(results))
"""


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> list:
    data_dir = tmp_path_factory.mktemp("answers") / "d"; data_dir.mkdir()
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir),
               PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "tests")]))
    r = subprocess.run([sys.executable, "-c", textwrap.dedent(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, f"stdout={r.stdout[-1500:]}\nstderr={r.stderr[-3500:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_every_cell_the_old_form_let_through_is_reachable_in_the_new_one(results):
    assert len(results) > 100, "the matrix is the whole set of reachable answers"
    refused = [(r["key"], r["errors"]) for r in results if r["errors"]]
    assert not refused, refused[:5]


def test_every_cell_hands_apply_camera_review_the_answers_the_old_form_handed_it(results):
    different = [(r["key"], r["saved"], r["want"]) for r in results if r["saved"] != r["want"]]
    assert not different, different[:5]


def test_an_answer_taken_away_is_asked_for_and_nothing_else_is(results):
    wrong = []
    for r in results:
        for name, asked in r["gone"]:
            if asked != [name if name not in ("level",) else "level"]:
                wrong.append((r["key"], name, asked))
    assert not wrong, wrong[:5]
