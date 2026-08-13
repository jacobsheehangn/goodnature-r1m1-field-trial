"""Regression test for the missing save-concurrency guard found in the
2026-08-13 UX audit.

save_data() used to be an unconditional full-workbook overwrite with no check
that the on-disk file was still the version this session's data was loaded
from - two operators saving around the same time (plausible in a multi-site
field trial) could silently clobber each other's work with no error to either.

The fix tracks the mtime a session's data was loaded at in st.session_state
(set once, right after the real app's single top-level `load_data()` call) and
has save_data() reject (st.error + st.stop, matching this file's other
hard-failure paths) a save made against a workbook that has since changed.
The check is opt-in via session_state, so it's inert for every existing
bare-mode test that calls save_data() directly - confirmed by the full suite
still passing unchanged.

Runs the real app.py functions directly in a subprocess (no import guard -
see test_derived_sheets.py), simulating st.session_state exactly as the real
top-level script would.
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
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_save_is_rejected_when_the_file_changed_since_this_session_loaded(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json, app
        import streamlit as st

        # Establish an initial saved state and record the mtime "my" session
        # loaded it at - exactly what the real top-level script does right
        # after load_data().
        data = app.create_sample_data()
        app.save_data(data)
        my_loaded_mtime = app._data_file_mtime()
        st.session_state[app.DATA_LOADED_MTIME_KEY] = my_loaded_mtime

        # My own in-memory edit, based on that snapshot.
        my_data = {name: frame.copy(deep=True) for name, frame in data.items()}
        my_data["Traps"].at[0, "Notes"] = "my concurrent edit"

        # Someone else saves a different change in the meantime - simulate by
        # clearing the tracked mtime for this "other" save so it isn't itself
        # blocked, then restoring my session's now-stale value afterward.
        other_data = {name: frame.copy(deep=True) for name, frame in data.items()}
        other_data["Traps"].at[0, "Notes"] = "someone else's concurrent edit"
        del st.session_state[app.DATA_LOADED_MTIME_KEY]
        app.save_data(other_data)
        other_mtime = app._data_file_mtime()

        st.session_state[app.DATA_LOADED_MTIME_KEY] = my_loaded_mtime

        # My save should now be rejected - the file moved since I "loaded".
        app.save_data(my_data)

        reloaded = app.load_data()
        print(json.dumps({
            "mtimes_differ": my_loaded_mtime != other_mtime,
            "final_notes": reloaded["Traps"].iloc[0]["Notes"],
            "tracked_mtime_after_rejected_save": st.session_state[app.DATA_LOADED_MTIME_KEY],
            "my_loaded_mtime": my_loaded_mtime,
            "other_mtime": other_mtime,
        }))
        """,
    )
    assert out["mtimes_differ"], "test setup assumption failed: the two saves must have produced different mtimes"
    assert out["final_notes"] == "someone else's concurrent edit", (
        "the conflicting save must have been rejected, not silently applied over the other write"
    )
    # A rejected save must bail out before reaching the post-write tracking
    # update, so the session's tracked mtime stays at its stale, pre-conflict
    # value rather than silently advancing to match the other save.
    assert out["tracked_mtime_after_rejected_save"] == out["my_loaded_mtime"]
    assert out["tracked_mtime_after_rejected_save"] != out["other_mtime"]


def test_normal_single_session_save_is_not_blocked_by_its_own_prior_save(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json, app
        import streamlit as st

        data = app.create_sample_data()
        app.save_data(data)
        st.session_state[app.DATA_LOADED_MTIME_KEY] = app._data_file_mtime()

        # A normal single-session edit-then-save, same shape as any real page
        # handler: load once, edit, save. Must succeed without a conflict,
        # and must keep tracking updated so a *second* normal save in the
        # same or a later rerun also isn't spuriously blocked.
        data["Traps"].at[0, "Notes"] = "first edit"
        app.save_data(data)
        data["Traps"].at[0, "Notes"] = "second edit"
        app.save_data(data)

        reloaded = app.load_data()
        print(json.dumps({"final_notes": reloaded["Traps"].iloc[0]["Notes"]}))
        """,
    )
    assert out["final_notes"] == "second edit"


def test_conflict_check_is_inert_without_session_tracking(tmp_path: Path) -> None:
    """The many existing tests that call save_data() directly (no session_state
    tracking set up at all) must be completely unaffected - this is what makes
    the fix safe to land without touching any of the ~36 other save_data() call
    sites throughout app.py."""
    out = _run(
        tmp_path,
        """
        import json, app
        data = app.create_sample_data()
        app.save_data(data)
        data["Traps"].at[0, "Notes"] = "untracked save"
        app.save_data(data)
        reloaded = app.load_data()
        print(json.dumps({"final_notes": reloaded["Traps"].iloc[0]["Notes"]}))
        """,
    )
    assert out["final_notes"] == "untracked save"
