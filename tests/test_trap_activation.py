"""Tests for activate_trap() / deactivate_trap() (Trap activation window brief).

Runs the real app.py in a subprocess rather than importing it in-process -
see test_derived_sheets.py for why (app.py runs Streamlit page-routing at
module level with no import guard).
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


def test_activating_an_inactive_trap_opens_exactly_one_window(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json, app
        from datetime import datetime
        data = app.create_sample_data()
        trap_id = data["Traps"][data["Traps"]["Status"] == "Inactive"].iloc[0]["Trap ID"] \\
            if (data["Traps"]["Status"] == "Inactive").any() else data["Traps"].iloc[0]["Trap ID"]
        idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
        data["Traps"].at[idx, "Status"] = "Inactive"
        # Sample data seeds an open window per trap - a real Inactive trap has
        # none open (deactivate_trap() always closes it), so clear the stale
        # one here to match that precondition instead of forcing an
        # impossible state (Inactive trap with an open window).
        data["Windows"] = data["Windows"][data["Windows"]["Trap ID"] != trap_id].copy()
        before_window_count = len(data["Windows"])
        effective = datetime(2026, 8, 13, 9, 30)
        app.activate_trap(data, trap_id, effective, "New trap deployed for field pass")
        reloaded = app.load_data()
        trap_row = reloaded["Traps"][reloaded["Traps"]["Trap ID"] == trap_id].iloc[0]
        window = app.open_window(reloaded, trap_id)
        audit = reloaded["Audit Log"]
        audit_row = audit[(audit["Record Type"] == "Trap") & (audit["Record ID"] == trap_id) & (audit["Field"] == "Status")]
        print(json.dumps({
            "status": trap_row["Status"],
            "window_count": len(reloaded["Windows"]) - before_window_count,
            "window_found": window is not None,
            "window_start": str(window["Start Time"]) if window is not None else None,
            "audit_rows": len(audit_row),
            "audit_new_value": audit_row.iloc[-1]["New Value"] if len(audit_row) else None,
        }))
        """,
    )
    assert out["status"] == "Active"
    assert out["window_count"] == 1
    assert out["window_found"] is True
    assert out["window_start"] == "2026-08-13 09:30:00"
    assert out["audit_rows"] >= 1
    assert out["audit_new_value"] == "Active"


def test_activating_an_already_active_trap_raises(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json, app
        from datetime import datetime
        data = app.create_sample_data()
        trap_id = data["Traps"].iloc[0]["Trap ID"]
        idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
        data["Traps"].at[idx, "Status"] = "Active"
        raised = False
        try:
            app.activate_trap(data, trap_id, datetime(2026, 8, 13, 9, 0), "test")
        except ValueError:
            raised = True
        print(json.dumps({"raised": raised}))
        """,
    )
    assert out["raised"] is True


def test_deactivating_an_active_trap_closes_open_window_and_opens_none(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json, app
        from datetime import datetime
        data = app.create_sample_data()
        trap_id = data["Traps"].iloc[0]["Trap ID"]
        idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
        data["Traps"].at[idx, "Status"] = "Inactive"
        # Sample data seeds an open window per trap - clear it so this test's
        # own activate_trap() call is what creates the window under test.
        data["Windows"] = data["Windows"][data["Windows"]["Trap ID"] != trap_id].copy()
        app.activate_trap(data, trap_id, datetime(2026, 8, 10, 8, 0), "activate for test")
        data = app.load_data()
        window_before = app.open_window(data, trap_id)
        assert window_before is not None, "test setup failed: no open window before deactivation"
        window_count_before = len(data["Windows"])

        effective = datetime(2026, 8, 13, 17, 0)
        app.deactivate_trap(data, trap_id, effective, "End of trial for this trap")

        reloaded = app.load_data()
        trap_row = reloaded["Traps"][reloaded["Traps"]["Trap ID"] == trap_id].iloc[0]
        closed = reloaded["Windows"][reloaded["Windows"]["Window ID"] == window_before["Window ID"]].iloc[0]
        still_open = app.open_window(reloaded, trap_id)
        print(json.dumps({
            "status": trap_row["Status"],
            "window_count_unchanged": len(reloaded["Windows"]) == window_count_before,
            "closed_status": closed["Status"],
            "closed_end_time": str(closed["End Time"]),
            "closed_end_reason": closed["End Reason"],
            "closed_review_status": closed["Review Status"],
            "still_open": still_open is not None,
        }))
        """,
    )
    assert out["status"] == "Inactive"
    assert out["window_count_unchanged"] is True
    assert out["closed_status"] == "Closed"
    assert out["closed_end_time"] == "2026-08-13 17:00:00"
    assert out["closed_end_reason"] == "Trap deactivated"
    assert out["closed_review_status"] == "Not required"
    assert out["still_open"] is False


def test_deactivating_a_trap_with_no_open_window_does_not_error(tmp_path: Path) -> None:
    """Shouldn't normally happen, but the brief explicitly says don't assume it can't."""
    out = _run(
        tmp_path,
        """
        import json, app
        from datetime import datetime
        data = app.create_sample_data()
        trap_id = data["Traps"].iloc[0]["Trap ID"]
        idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
        data["Traps"].at[idx, "Status"] = "Active"
        # No window ever opened for this trap - simulates the exact bug this brief fixes,
        # caught retroactively (an Active trap somehow has no open window). Sample data
        # seeds an open window per trap by default, so clear it for this trap first.
        data["Windows"] = data["Windows"][data["Windows"]["Trap ID"] != trap_id].copy()
        app.save_data(data)
        data = app.load_data()
        assert app.open_window(data, trap_id) is None, "test setup failed: unexpectedly has an open window"

        error = None
        try:
            app.deactivate_trap(data, trap_id, datetime(2026, 8, 13, 12, 0), "test - no window case")
        except Exception as exc:
            error = repr(exc)

        reloaded = app.load_data()
        trap_row = reloaded["Traps"][reloaded["Traps"]["Trap ID"] == trap_id].iloc[0]
        print(json.dumps({"error": error, "status": trap_row["Status"]}))
        """,
    )
    assert out["error"] is None
    assert out["status"] == "Inactive"


def test_deactivating_an_already_inactive_trap_raises(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        """
        import json, app
        from datetime import datetime
        data = app.create_sample_data()
        trap_id = data["Traps"].iloc[0]["Trap ID"]
        idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
        data["Traps"].at[idx, "Status"] = "Inactive"
        raised = False
        try:
            app.deactivate_trap(data, trap_id, datetime(2026, 8, 13, 9, 0), "test")
        except ValueError:
            raised = True
        print(json.dumps({"raised": raised}))
        """,
    )
    assert out["raised"] is True


def test_commit_false_defers_save(tmp_path: Path) -> None:
    """Phase 2's bulk tool relies on commit=False + one shared save_data() at the end."""
    out = _run(
        tmp_path,
        """
        import json, app
        from datetime import datetime
        data = app.create_sample_data()
        trap_id = data["Traps"].iloc[0]["Trap ID"]
        idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
        data["Traps"].at[idx, "Status"] = "Inactive"
        app.save_data(data)
        data = app.load_data()

        app.activate_trap(data, trap_id, datetime(2026, 8, 13, 9, 0), "deferred commit test", commit=False)
        # In-memory data reflects the change immediately even without a save.
        in_memory_status = data["Traps"][data["Traps"]["Trap ID"] == trap_id].iloc[0]["Status"]
        # But nothing hit disk yet.
        on_disk = app.load_data()
        on_disk_status = on_disk["Traps"][on_disk["Traps"]["Trap ID"] == trap_id].iloc[0]["Status"]

        app.save_data(data)
        reloaded = app.load_data()
        final_status = reloaded["Traps"][reloaded["Traps"]["Trap ID"] == trap_id].iloc[0]["Status"]
        print(json.dumps({
            "in_memory_status": in_memory_status,
            "on_disk_status_before_save": on_disk_status,
            "final_status_after_save": final_status,
        }))
        """,
    )
    assert out["in_memory_status"] == "Active"
    assert out["on_disk_status_before_save"] == "Inactive"
    assert out["final_status_after_save"] == "Active"


def test_add_trap_creation_path_still_starts_window_when_active(tmp_path: Path) -> None:
    """Regression risk from the brief: Add trap (creation) must be completely
    unaffected by this brief - it already calls start_window() correctly."""
    out = _run(
        tmp_path,
        """
        import json, app
        data = app.create_sample_data()
        row = {c: "" for c in app.SHEETS["Traps"]}
        existing_trap = data["Traps"].iloc[0]
        row.update({
            "Trap ID": "TEST-NEW-TRAP-1", "Product": existing_trap["Product"],
            "Build Version": existing_trap["Build Version"], "Site ID": existing_trap["Site ID"],
            "Route Order": "99", "Status": "Active",
            "Deployment Start": app.dtstr(app.now()),
        })
        import pandas as pd
        data["Traps"] = pd.concat([data["Traps"], pd.DataFrame([row])], ignore_index=True)
        data["Traps"] = data["Traps"][app.SHEETS["Traps"]]
        app.start_window(data, "TEST-NEW-TRAP-1", app.now())
        app.save_data(data)
        reloaded = app.load_data()
        window = app.open_window(reloaded, "TEST-NEW-TRAP-1")
        print(json.dumps({"window_found": window is not None}))
        """,
    )
    assert out["window_found"] is True


def _bulk_activation_script(force_error_on: str = "") -> str:
    """Mirrors the bulk-activate UI's own loop exactly: activate_trap(...,
    commit=False) per selected trap inside a try/except, one save_data() at
    the end. force_error_on pre-activates one trap (outside the batch) so
    the batch's own call to it raises ValueError, same as a real mid-batch
    failure - Phase 2's test criteria wants this proven, not assumed safe."""
    return f"""
        import json, app
        from datetime import datetime
        data = app.create_sample_data()
        trap_ids = data["Traps"].iloc[0:3]["Trap ID"].tolist()
        for tid in trap_ids:
            idx = data["Traps"].index[data["Traps"]["Trap ID"] == tid][0]
            data["Traps"].at[idx, "Status"] = "Inactive"
            data["Windows"] = data["Windows"][data["Windows"]["Trap ID"] != tid].copy()
        app.save_data(data)
        data = app.load_data()

        force_error_on = {force_error_on!r}
        if force_error_on:
            app.activate_trap(data, force_error_on, datetime(2026, 8, 13, 8, 0), "pre-activated to force a batch error")

        shared_dt = datetime(2026, 8, 13, 9, 0)
        individual_times = {{trap_ids[1]: datetime(2026, 8, 13, 11, 30)}}

        applied, skipped = [], []
        for tid in trap_ids:
            effective = individual_times.get(tid, shared_dt)
            try:
                app.activate_trap(data, tid, effective, "bulk test batch", commit=False)
                applied.append(tid)
            except ValueError as exc:
                skipped.append(tid)
        if applied:
            app.save_data(data)

        reloaded = app.load_data()
        results = {{}}
        for tid in trap_ids:
            trow = reloaded["Traps"][reloaded["Traps"]["Trap ID"] == tid].iloc[0]
            window = app.open_window(reloaded, tid)
            audit = reloaded["Audit Log"]
            audit_rows = audit[(audit["Record Type"] == "Trap") & (audit["Record ID"] == tid) & (audit["Field"] == "Status") & (audit["New Value"] == "Active")]
            results[tid] = {{
                "status": trow["Status"],
                "window_start": str(window["Start Time"]) if window is not None else None,
                "audit_count": len(audit_rows),
            }}
        print(json.dumps({{"applied": applied, "skipped": skipped, "results": results, "trap_ids": trap_ids}}))
        """


def test_bulk_activation_batch_of_three_each_gets_correct_window_and_audit(tmp_path: Path) -> None:
    out = _run(tmp_path, _bulk_activation_script())
    trap_ids = out["trap_ids"]
    assert out["applied"] == trap_ids
    assert out["skipped"] == []
    for tid in trap_ids:
        r = out["results"][tid]
        assert r["status"] == "Active"
        assert r["window_start"] is not None
        assert r["audit_count"] == 1


def test_bulk_activation_mixes_shared_and_individual_times_correctly(tmp_path: Path) -> None:
    out = _run(tmp_path, _bulk_activation_script())
    trap_ids = out["trap_ids"]
    shared_result = out["results"][trap_ids[0]]
    individual_result = out["results"][trap_ids[1]]
    other_shared_result = out["results"][trap_ids[2]]
    assert shared_result["window_start"] == "2026-08-13 09:00:00"
    assert other_shared_result["window_start"] == "2026-08-13 09:00:00"
    assert individual_result["window_start"] == "2026-08-13 11:30:00"


def test_bulk_activation_error_on_one_trap_does_not_corrupt_or_skip_the_others(tmp_path: Path) -> None:
    """Same failure-isolation standard as every other bulk write this session:
    one trap already Active (simulating a mid-batch failure) must not
    partially-apply or corrupt the batch - the other two still activate
    correctly, and the failed one is cleanly skipped, not left broken."""
    script = """
        import json, app
        data = app.create_sample_data()
        trap_ids = data["Traps"].iloc[0:3]["Trap ID"].tolist()
        print(json.dumps({"trap_ids": trap_ids}))
        """
    ids_out = _run(tmp_path, script)
    force_trap = ids_out["trap_ids"][0]

    out = _run(tmp_path, _bulk_activation_script(force_error_on=force_trap))
    trap_ids = out["trap_ids"]
    assert out["applied"] == trap_ids[1:]
    assert out["skipped"] == [trap_ids[0]]
    # The pre-activated trap is untouched by the batch (still Active, from
    # the setup activation, not corrupted by the failed batch attempt).
    assert out["results"][trap_ids[0]]["status"] == "Active"
    assert out["results"][trap_ids[0]]["audit_count"] == 1
    # The other two still activated correctly despite the batch containing a failure.
    for tid in trap_ids[1:]:
        r = out["results"][tid]
        assert r["status"] == "Active"
        assert r["window_start"] is not None
        assert r["audit_count"] == 1
