"""Tests for the Phase 1 derived Trial Config / Kills sheets (Trial performance brief).

Runs the real app.py in a subprocess rather than importing it in-process -
app.py runs Streamlit page-routing at module level with no import guard
(see test_site_urgency.py), so a subprocess gives each test a clean
interpreter, the same approach conftest.py's own `local_app` fixture uses
to launch the real app for the Playwright suite.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(tmp_path: Path, script: str) -> dict:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "R1M1_ENVIRONMENT": "local",
            "R1M1_ALLOW_NO_AUTH": "true",
            "R1M1_SEED_MODE": "clean",
            "R1M1_DATA_DIR": str(data_dir),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_trial_config_reflects_the_code_constant(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json, app
        data = app.create_sample_data()
        app.save_data(data)
        reloaded = app.load_data()
        tc = reloaded["Trial Config"]
        row = tc[tc["Parameter"] == "Time to kill target (minutes)"].iloc[0]
        print(json.dumps({
            "value": row["Value"],
            "source": row["Source"],
            "set_date": row["Set Date"],
            "expected_value": str(app.TIME_TO_KILL_TARGET_MINUTES),
            "expected_source": app.TIME_TO_KILL_TARGET_SOURCE,
        }))
        """,
    )
    assert out["value"] == out["expected_value"] == "1440"
    assert out["source"] == out["expected_source"]
    assert out["set_date"]


def test_kills_sheet_row_count_matches_physical_kill_population(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json, app
        data = app.create_sample_data()
        app.save_data(data)
        reloaded = app.load_data()
        expected = len(app.physical_kill_population(reloaded["Windows"]))
        actual = len(reloaded["Kills"])
        print(json.dumps({"expected": expected, "actual": actual, "columns": list(reloaded["Kills"].columns)}))
        """,
    )
    assert out["actual"] == out["expected"]
    assert out["columns"] == [
        "Window ID", "Trap ID", "Site ID", "Build Version", "Kill Time",
        "Final Humane Kill", "Interaction To Kill Min", "Necropsy Assessment",
        "Animal Weight Range", "Bag ID",
    ]


def test_kills_sheet_is_a_live_view_not_a_stale_snapshot(tmp_path: Path) -> None:
    """Editing a kill's Final Humane Kill and saving again must update the Kills sheet.

    create_sample_data() (clean seed) has no confirmed kills by default, so this
    test synthesizes one physical-kill window rather than relying on the sample
    data happening to contain one.
    """
    out = _run(
        tmp_path,
        """
        import json, app
        data = app.create_sample_data()
        window_id = "TEST-KILL-WINDOW-1"
        row = {c: "" for c in app.SHEETS["Windows"]}
        row.update({
            "Window ID": window_id, "Trap ID": data["Traps"].iloc[0]["Trap ID"],
            "Product": data["Traps"].iloc[0]["Product"], "Build Version": data["Traps"].iloc[0]["Build Version"],
            "Site ID": data["Traps"].iloc[0]["Site ID"], "Status": "Closed",
            "Start Time": "2026-08-01 00:00:00", "End Time": "2026-08-02 00:00:00",
            "Finding At Close": "Dead animal found", "Final Humane Kill": "Pending",
        })
        import pandas as pd
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([row])], ignore_index=True)
        app.save_data(data)
        data = app.load_data()
        idx = data["Windows"].index[data["Windows"]["Window ID"] == window_id][0]
        data["Windows"].at[idx, "Final Humane Kill"] = "Yes"
        app.save_data(data)
        reloaded = app.load_data()
        kills_row = reloaded["Kills"][reloaded["Kills"]["Window ID"] == window_id].iloc[0]
        print(json.dumps({"kills_sheet_value": kills_row["Final Humane Kill"]}))
        """,
    )
    assert out["kills_sheet_value"] == "Yes"


def test_no_ui_widget_writes_to_the_derived_sheets() -> None:
    """Concrete check, not a visual one - confirm no input widget is bound to Trial Config/Kills."""
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    for needle in ['data["Trial Config"]', 'data["Kills"]', "data['Trial Config']", "data['Kills']"]:
        assert needle not in source, f"found a direct reference to {needle} outside _derived_sheet_data/SHEETS"


def test_derivation_failure_does_not_block_or_corrupt_an_unrelated_save(tmp_path: Path) -> None:
    """The single most important test in this brief's Phase 1: force an error in the
    derived-sheet computation and confirm every other sheet still saves correctly."""
    out = _run(
        tmp_path,
        """
        import json, app

        def _boom(data):
            raise RuntimeError("forced failure for test")

        app._derived_sheet_data = _boom

        data = app.create_sample_data()
        before_trap_count = len(data["Traps"])
        data["Traps"].at[data["Traps"].index[0], "Notes"] = "edited during forced derivation failure"
        app.save_data(data)

        reloaded = app.load_data()
        print(json.dumps({
            "trap_count": len(reloaded["Traps"]),
            "expected_trap_count": before_trap_count,
            "edited_note": reloaded["Traps"].iloc[0]["Notes"],
            "sites_count": len(reloaded["Sites"]),
            "expected_sites_count": len(data["Sites"]),
        }))
        """,
    )
    assert out["trap_count"] == out["expected_trap_count"]
    assert out["edited_note"] == "edited during forced derivation failure"
    assert out["sites_count"] == out["expected_sites_count"]
