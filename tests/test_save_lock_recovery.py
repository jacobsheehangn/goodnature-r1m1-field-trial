"""Regression test for the failed-save stranding bug found in the 2026-08-13 UX audit.

commit_staged_records_with_photos() is the shared commit path for the check-save
and necropsy-save flows. On failure it rolls back, logs, shows an error, and calls
st.stop() - which halts the real Streamlit script immediately, so any caller-side
cleanup written *after* the call (like popping a save-in-progress lock key) never
ran. That left the check page's Save button permanently disabled on the next
rerun after any failed save (workbook write conflict, disk error, etc.) - exactly
the failure mode the app is built to expect on a patchy field connection.

The fix passes session_state_keys_to_clear_on_failure so the lock is cleared
inside the function itself, before st.stop(), regardless of what the caller does
afterward. Runs the real function in a subprocess (app.py has no import guard -
see test_derived_sheets.py) with save_data() monkeypatched to force the failure
path deterministically.
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


def test_lock_key_is_cleared_when_the_commit_fails(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json, app
        import streamlit as st

        def _boom(data):
            raise RuntimeError("forced save failure for test")

        app.save_data = _boom

        data = app.create_sample_data()
        staged = {name: frame.copy(deep=True) for name, frame in data.items()}
        original_data = {name: frame.copy(deep=True) for name, frame in data.items()}

        st.session_state["test_save_lock"] = True
        st.session_state["unrelated_key"] = "still here"

        app.commit_staged_records_with_photos(
            data=data,
            staged=staged,
            original_data=original_data,
            photo_gate={},
            expected_photo_count=0,
            record_id="TEST-CHK-001",
            photos_id_column="Check ID",
            verify_persisted=lambda reloaded: {},
            log_prefix="test",
            log_fields={},
            record_noun="test record",
            record_description="test record",
            session_state_keys_to_clear_on_failure=["test_save_lock"],
        )

        print(json.dumps({
            "lock_key_present": "test_save_lock" in st.session_state,
            "unrelated_key_present": "unrelated_key" in st.session_state,
        }))
        """,
    )
    assert out["lock_key_present"] is False
    assert out["unrelated_key_present"] is True


def test_no_keys_to_clear_is_a_safe_default(tmp_path: Path) -> None:
    """Calling without the new parameter (the necropsy/data-management call sites,
    which don't pass it) must not raise - confirms the default is safe."""
    out = _run(
        tmp_path,
        """
        import json, app
        import streamlit as st

        def _boom(data):
            raise RuntimeError("forced save failure for test")

        app.save_data = _boom

        data = app.create_sample_data()
        staged = {name: frame.copy(deep=True) for name, frame in data.items()}
        original_data = {name: frame.copy(deep=True) for name, frame in data.items()}

        app.commit_staged_records_with_photos(
            data=data,
            staged=staged,
            original_data=original_data,
            photo_gate={},
            expected_photo_count=0,
            record_id="TEST-CHK-002",
            photos_id_column="Check ID",
            verify_persisted=lambda reloaded: {},
            log_prefix="test",
            log_fields={},
            record_noun="test record",
            record_description="test record",
        )

        print(json.dumps({"ok": True}))
        """,
    )
    assert out["ok"] is True
