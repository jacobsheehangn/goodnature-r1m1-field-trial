"""Phase 1 (TRIAL_LIFECYCLE_BRIEF.md): the Trial model.

A Trial is a real record (`Trials` sheet, `Windows.Trial ID`). One guard in
activate_trap() enforces "Active only at a site with an Open trial, on a
declared build" (T2/T3); start_window() stamps the open trial and must never
raise (T4); a build never changes inside a trial (T5); only Inactive traps move
(T6). This file covers the logic and the table of paths; the Add trap form, the
bulk-activate expander and a real check save are in test_trial_model_ui.py.

Runs the real app.py in a subprocess (see test_derived_sheets.py for why)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app.py").read_text()

_COMMON = """
    import json, datetime, os, app, pandas as pd
    data = app.create_sample_data()
    site_a = data["Traps"].iloc[0]["Site ID"]
    site_b = data["Traps"][data["Traps"]["Site ID"] != site_a].iloc[0]["Site ID"]
    site_c = [s for s in data["Sites"]["Site ID"] if s not in (site_a, site_b)][0]
    LABEL_R1, LABEL_R1_OLD, LABEL_M1 = "R1 · R1 Build 4.3", "R1 · R1 Build 4.2", "M1 · M1 Build 3.7"
    when = datetime.datetime(2026, 9, 1, 9, 0)
    r1_traps_a = [t for t in data["Traps"][data["Traps"]["Site ID"] == site_a]["Trap ID"] if t.startswith("R1")]

    def trap(d, trap_id):
        return d["Traps"][d["Traps"]["Trap ID"] == trap_id].iloc[0]

    def open_windows(d, trap_id):
        w = d["Windows"]
        return w[(w["Trap ID"] == trap_id) & (w["Status"] == "Open")]

    def stage_inactive(trap_ids):
        # An Inactive trap has no open window (deactivate_trap closes it).
        for t in trap_ids:
            app.deactivate_trap(data, t, when, "stage", commit=False)

    def attempt(fn, *a, **k):
        try:
            fn(*a, **k)
            return "ok"
        except ValueError as exc:
            return str(exc)

    def snapshot(d):
        return json.dumps([d["Traps"].to_json(), d["Windows"].to_json(), len(d["Audit Log"]), d["Trials"].to_json()])
"""


def _run(script: str, extra_env: dict | None = None) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "R1M1_ENVIRONMENT": "local",
            "R1M1_ALLOW_NO_AUTH": "true",
            "R1M1_SEED_MODE": "clean",
            "R1M1_DATA_DIR": tempfile.mkdtemp(),
        }
    )
    env.update(extra_env or {})
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_COMMON) + textwrap.dedent(script)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr[-3000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


# --- schema and migration -----------------------------------------------------

def test_a_workbook_from_before_the_trial_model_loads_and_saves_cleanly() -> None:
    """No manual migration: the Trials sheet appears blank and Windows/Kills gain a blank Trial ID."""
    out = _run(
        """
        app.save_data(data)
        sheets = pd.read_excel(app.DATA_FILE, sheet_name=None, dtype=str)
        sheets.pop("Trials")
        sheets["Windows"] = sheets["Windows"].drop(columns=["Trial ID"])
        sheets["Kills"] = sheets["Kills"].drop(columns=["Trial ID"])
        with pd.ExcelWriter(app.DATA_FILE) as writer:
            for name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=name, index=False)
        # The workbook was rewritten behind the app's back, so tell it that is the version in hand
        # (otherwise save_data() rightly rejects the save as stale).
        app.st.session_state[app.DATA_LOADED_MTIME_KEY] = app._data_file_mtime()
        old = app.load_data()
        windows_before = len(old["Windows"])
        app.save_data(old)
        fresh = pd.read_excel(app.DATA_FILE, sheet_name=None, dtype=str)
        print(json.dumps({
            "trials_columns": list(old["Trials"].columns), "trials_rows": len(old["Trials"]),
            "windows_has_column": "Trial ID" in old["Windows"].columns,
            "windows_trial_ids_blank": bool((old["Windows"]["Trial ID"] == "").all()),
            "after_save_has_trials_sheet": "Trials" in fresh, "windows_kept": len(fresh["Windows"]) == windows_before,
        }))
        """
    )
    assert out["trials_columns"] == ["Trial ID", "Site ID", "Status", "Start Time", "End Time", "Declared Builds", "Origin", "Notes"]
    assert out["trials_rows"] == 0
    assert out["windows_has_column"] and out["windows_trial_ids_blank"]
    assert out["after_save_has_trials_sheet"] and out["windows_kept"]


def test_a_backup_made_before_the_trial_model_can_still_be_restored() -> None:
    """restore_backup() used to demand every sheet; every backup taken before the
    Trials sheet existed would have been refused, which is the one moment a
    rollback is most likely to be needed."""
    out = _run(
        """
        app.save_data(data)
        sheets = pd.read_excel(app.DATA_FILE, sheet_name=None, dtype=str)
        for derived in ("Trials", "Trial Config", "Kills"):
            sheets.pop(derived)
        sheets["Windows"] = sheets["Windows"].drop(columns=["Trial ID"])
        backup = app.BACKUP_DIR / (app.DATA_FILE.stem + "_pre_phase1.xlsx")
        with pd.ExcelWriter(backup) as writer:
            for name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=name, index=False)
        app.restore_backup(backup)
        restored = app.load_data()
        # A backup that is genuinely missing a required sheet is still refused.
        broken = app.BACKUP_DIR / (app.DATA_FILE.stem + "_broken.xlsx")
        with pd.ExcelWriter(broken) as writer:
            sheets["Traps"].to_excel(writer, sheet_name="Traps", index=False)
        refusal = attempt(app.restore_backup, broken)
        print(json.dumps({"trials_rows": len(restored["Trials"]), "traps": len(restored["Traps"]), "refusal": refusal}))
        """
    )
    assert out["trials_rows"] == 0 and out["traps"] > 0
    assert out["refusal"].startswith("Backup is missing sheets:") and "Trials" not in out["refusal"]


def test_the_trials_sheet_is_in_every_backup_copy_and_a_site_rename_follows_it() -> None:
    out = _run(
        """
        app.create_trial(data, site_a, [LABEL_R1], when)
        app.save_data(data)
        app.save_data(app.load_data())  # a second save copies the first into the backup folder
        backup = sorted(app.BACKUP_DIR.glob(app.DATA_FILE.stem + "_*.xlsx"))[-1]
        in_backup = pd.read_excel(backup, sheet_name=None, dtype=str)
        updated, counts, _moves = app.rename_site_code(app.load_data(), site_a, "ZZZ", "rename for test")
        print(json.dumps({
            "backup_has_trials": "Trials" in in_backup and len(in_backup["Trials"]) == 1,
            "renamed_site": updated["Trials"].iloc[0]["Site ID"],
            "link_counts_include_trials": counts.get("Trials"),
        }))
        """
    )
    assert out["backup_has_trials"]
    assert out["renamed_site"] == "ZZZ", "a trial must follow its site through a rename or it is orphaned"
    assert out["link_counts_include_trials"] == 1, "the rename preview counts the trial among the linked records"


# --- create_trial: T1 and the declared-build rules ------------------------------

def test_create_trial_enforces_one_open_trial_per_site_and_valid_builds() -> None:
    out = _run(
        """
        first = app.create_trial(data, site_a, [LABEL_R1], when)
        results = {"first": first, "duplicate": attempt(app.create_trial, data, site_a, [LABEL_R1], when)}
        results["other_site_ok"] = attempt(app.create_trial, data, site_b, [LABEL_R1], when)
        results["none"] = attempt(app.create_trial, data, site_c, [], when)
        results["four"] = attempt(app.create_trial, data, site_c, ["a", "b", "c", "d"], when)
        results["unknown_build"] = attempt(app.create_trial, data, site_c, ["R1 · R1 Build 9.9"], when)
        results["mixed_products"] = attempt(app.create_trial, data, site_c, [LABEL_R1, LABEL_M1], when)
        results["unknown_site"] = attempt(app.create_trial, data, "NOPE", [LABEL_R1], when)
        results["rows_after_refusals"] = len(data["Trials"])
        row = data["Trials"].iloc[0]
        results["row"] = {c: row[c] for c in app.SHEETS["Trials"]}
        results["audit"] = data["Audit Log"].iloc[-2:][["Record Type", "Field", "New Value"]].values.tolist()
        print(json.dumps(results))
        """
    )
    assert out["first"].startswith("TRIAL-") and out["first"].endswith("-01")
    assert out["duplicate"] == "This site already has a trial running."
    assert out["other_site_ok"] == "ok"
    assert "1 to 3" in out["none"] and "1 to 3" in out["four"]
    assert out["unknown_build"].startswith("Unknown build")
    assert "same product" in out["mixed_products"]
    assert out["unknown_site"] == "That site could not be found."
    assert out["rows_after_refusals"] == 2, "only the two valid trials were created; every refusal left the sheet alone"
    assert out["row"]["Status"] == "Open" and out["row"]["End Time"] == "" and out["row"]["Origin"] == "Started"
    assert out["row"]["Declared Builds"] == "R1 · R1 Build 4.3" and out["row"]["Start Time"] == "2026-09-01 09:00:00"
    assert ["Trial", "Status", "Open"] in out["audit"]


def test_trial_ids_are_a_per_site_sequence_unlike_bag_trap_or_window_ids() -> None:
    out = _run(
        """
        a = app.create_trial(data, site_a, [LABEL_R1], when)
        data["Trials"].loc[data["Trials"]["Trial ID"] == a, "Status"] = "Ended"
        b = app.create_trial(data, site_a, [LABEL_R1, LABEL_R1_OLD], when)
        c = app.create_trial(data, site_b, [LABEL_R1], when)
        print(json.dumps({"a": a, "b": b, "c": c, "site_a": site_a, "site_b": site_b,
                          "declared": app.trial_declared_builds(app.open_trial(data, site_a)),
                          "open_a": app.open_trial(data, site_a)["Trial ID"], "none": app.open_trial(data, site_c) is None}))
        """
    )
    assert out["a"] == f"TRIAL-{out['site_a']}-01" and out["b"] == f"TRIAL-{out['site_a']}-02"
    assert out["c"] == f"TRIAL-{out['site_b']}-01"
    assert out["declared"] == ["R1 · R1 Build 4.3", "R1 · R1 Build 4.2"]
    assert out["open_a"] == out["b"], "an Ended trial is never returned as the open one"
    assert out["none"] is True


# --- T4: start_window stamps, and never raises ------------------------------------

def test_start_window_stamps_the_open_trial_and_leaves_an_untracked_site_blank() -> None:
    out = _run(
        """
        trial_id = app.create_trial(data, site_a, [LABEL_R1], when)
        untracked = data["Traps"][data["Traps"]["Site ID"] == site_b].iloc[0]["Trap ID"]
        stage_inactive([r1_traps_a[0], untracked])
        stamped = app.start_window(data, r1_traps_a[0], when)
        unstamped = app.start_window(data, untracked, when)
        w = data["Windows"].set_index("Window ID")
        print(json.dumps({"trial": trial_id, "stamped": w.loc[stamped, "Trial ID"], "unstamped": w.loc[unstamped, "Trial ID"]}))
        """
    )
    assert out["stamped"] == out["trial"] and out["unstamped"] == ""


def test_start_window_never_raises_when_the_trial_lookup_fails() -> None:
    """The check-save flow calls start_window() (will_start). A trial lookup
    failing must never cost an operator a saved check: the window still opens,
    unstamped."""
    out = _run(
        """
        app.create_trial(data, site_a, [LABEL_R1], when)
        stage_inactive(r1_traps_a[:2])

        # 1. the test-only hook inside the lookup
        os.environ["R1M1_TEST_FORCE_TRIAL_LOOKUP_FAILURE"] = "1"
        forced = app.start_window(data, r1_traps_a[0], when)
        del os.environ["R1M1_TEST_FORCE_TRIAL_LOOKUP_FAILURE"]

        # 2. the lookup itself blowing up, whatever the cause
        real = app.open_trial
        def boom(*a, **k): raise RuntimeError("sheet unreadable")
        app.open_trial = boom
        patched = app.start_window(data, r1_traps_a[1], when)
        app.open_trial = real

        # 3. a damaged Trials sheet (column missing)
        broken = {k: v.copy() for k, v in data.items()}
        broken["Trials"] = broken["Trials"].drop(columns=["Status"])
        stage = app.start_window(broken, r1_traps_a[0], when)

        w = data["Windows"].set_index("Window ID")
        print(json.dumps({
            "forced_opened": bool(forced), "forced_trial_id": w.loc[forced, "Trial ID"], "forced_status": w.loc[forced, "Status"],
            "patched_opened": bool(patched), "patched_trial_id": w.loc[patched, "Trial ID"],
            "damaged_sheet_opened": bool(stage),
        }))
        """
    )
    assert out["forced_opened"] and out["forced_trial_id"] == "" and out["forced_status"] == "Open"
    assert out["patched_opened"] and out["patched_trial_id"] == ""
    assert out["damaged_sheet_opened"]


# --- the table of paths -----------------------------------------------------------

def test_path_2_activate_trap_passes_in_a_trial_on_a_declared_build_and_stamps_the_window() -> None:
    out = _run(
        """
        trial_id = app.create_trial(data, site_a, [LABEL_R1], when)
        stage_inactive(r1_traps_a[:1])
        app.activate_trap(data, r1_traps_a[0], when, "start", commit=False)
        w = open_windows(data, r1_traps_a[0])
        print(json.dumps({"status": trap(data, r1_traps_a[0])["Status"], "open": len(w), "stamp": w.iloc[0]["Trial ID"], "trial": trial_id}))
        """
    )
    assert out["status"] == "Active" and out["open"] == 1 and out["stamp"] == out["trial"]


def test_path_2_activate_trap_refuses_with_no_trial_and_changes_nothing() -> None:
    out = _run(
        """
        stage_inactive(r1_traps_a[:1])
        before = snapshot(data)
        message = attempt(app.activate_trap, data, r1_traps_a[0], when, "start", commit=False)
        print(json.dumps({"message": message, "unchanged": snapshot(data) == before, "site_name": app.site_name(data, site_a)}))
        """
    )
    assert out["message"] == f"No trial is running at {out['site_name']}. Start a trial first. Every active trap belongs to a trial."
    assert out["unchanged"], "a refused activation must not touch traps, windows, audit or trials"


def test_path_2_activate_trap_refuses_an_undeclared_build_and_changes_nothing() -> None:
    out = _run(
        """
        trial_id = app.create_trial(data, site_a, [LABEL_R1_OLD], when)
        stage_inactive(r1_traps_a[:1])
        before = snapshot(data)
        message = attempt(app.activate_trap, data, r1_traps_a[0], when, "start", commit=False)
        print(json.dumps({"message": message, "trial": trial_id, "unchanged": snapshot(data) == before}))
        """
    )
    assert out["message"] == (
        f"R1 · R1 Build 4.3 isn't part of {out['trial']}. Declared builds: R1 · R1 Build 4.2. "
        "Change this trap's build first (allowed while it's Inactive), then activate it."
    )
    assert out["unchanged"]


def test_path_2_a_trap_of_another_product_is_refused_by_the_same_guard() -> None:
    """T8: activating an M1 trap into an R1 trial is refused by T2, not by a second copy of the rule."""
    out = _run(
        """
        app.create_trial(data, site_a, [LABEL_R1], when)
        m1 = data["Traps"][(data["Traps"]["Site ID"] == site_a) & (data["Traps"]["Product"] == "M1")].iloc[0]["Trap ID"]
        stage_inactive([m1])
        print(json.dumps({"message": attempt(app.activate_trap, data, m1, when, "start", commit=False)}))
        """
    )
    assert "isn't part of" in out["message"] and "M1 · M1 Build 3.7" in out["message"]


def test_a_blank_deployment_start_is_set_at_first_activation_and_never_overwritten() -> None:
    out = _run(
        """
        app.create_trial(data, site_a, [LABEL_R1], when)
        stage_inactive(r1_traps_a[:2])
        for t in r1_traps_a[:2]:
            data["Traps"].loc[data["Traps"]["Trap ID"] == t, "Deployment Start"] = ""
        data["Traps"].loc[data["Traps"]["Trap ID"] == r1_traps_a[1], "Deployment Start"] = "2026-07-01 08:00:00"
        app.activate_trap(data, r1_traps_a[0], when, "first", commit=False)
        app.activate_trap(data, r1_traps_a[1], when, "re-activation", commit=False)
        print(json.dumps({"never_activated": trap(data, r1_traps_a[0])["Deployment Start"], "already_set": trap(data, r1_traps_a[1])["Deployment Start"]}))
        """
    )
    assert out["never_activated"] == "2026-09-01 09:00:00"
    assert out["already_set"] == "2026-07-01 08:00:00"


def test_path_8_change_trap_build() -> None:
    out = _run(
        """
        results = {}
        # Inactive: allowed, no window operations.
        stage_inactive(r1_traps_a[:1])
        windows_before = len(data["Windows"])
        results["inactive"] = attempt(app.change_trap_build, data, r1_traps_a[0], "R1", "R1 Build 4.2", when, "stage", commit=False)
        results["inactive_windows_added"] = len(data["Windows"]) - windows_before
        results["inactive_open"] = len(open_windows(data, r1_traps_a[0]))
        # Active at an untracked site: allowed as today (closes and opens a window).
        results["untracked"] = attempt(app.change_trap_build, data, r1_traps_a[1], "R1", "R1 Build 4.2", when, "change", commit=False)
        results["untracked_open"] = len(open_windows(data, r1_traps_a[1]))
        # Active in an Open trial: refused, and nothing changes.
        trial_id = app.create_trial(data, site_a, [LABEL_R1_OLD], when)
        before = snapshot(data)
        results["in_trial"] = attempt(app.change_trap_build, data, r1_traps_a[1], "R1", "R1 Build 4.3", when, "change", commit=False)
        results["in_trial_unchanged"] = snapshot(data) == before
        results["trial"] = trial_id
        print(json.dumps(results))
        """
    )
    assert out["inactive"] == "ok" and out["inactive_windows_added"] == 0 and out["inactive_open"] == 0
    assert out["untracked"] == "ok" and out["untracked_open"] == 1
    assert out["in_trial"] == (
        "A build can't change inside a trial. Changing a build starts a new trial. "
        f"End {out['trial']}, then start a new trial with the builds you want — the roster carries over."
    )
    assert out["in_trial_unchanged"]


def test_path_9_move_trap() -> None:
    out = _run(
        """
        results = {}
        stage_inactive(r1_traps_a[:1])
        results["inactive"] = attempt(app.move_trap, data, r1_traps_a[0], site_b, when, "stage", 9, "Spot", "", commit=False)
        results["inactive_open"] = len(open_windows(data, r1_traps_a[0]))
        results["inactive_site"] = trap(data, r1_traps_a[0])["Site ID"] == site_b
        before = snapshot(data)
        results["active"] = attempt(app.move_trap, data, r1_traps_a[1], site_b, when, "move", 9, "Spot", "", commit=False)
        results["active_unchanged"] = snapshot(data) == before
        print(json.dumps(results))
        """
    )
    assert out["inactive"] == "ok" and out["inactive_open"] == 0 and out["inactive_site"]
    assert out["active"] == (
        "Deactivate this trap before moving it. Leaving a trial ends its part in it. "
        "Deactivate, move, then activate it into the destination site's trial."
    )
    assert out["active_unchanged"]


def test_path_10_deactivate_is_unchanged_and_the_window_keeps_its_trial_id() -> None:
    out = _run(
        """
        trial_id = app.create_trial(data, site_a, [LABEL_R1], when)
        stage_inactive(r1_traps_a[:1])
        app.activate_trap(data, r1_traps_a[0], when, "start", commit=False)
        window_id = open_windows(data, r1_traps_a[0]).iloc[0]["Window ID"]
        app.deactivate_trap(data, r1_traps_a[0], when + datetime.timedelta(days=1), "end", commit=False)
        w = data["Windows"].set_index("Window ID").loc[window_id]
        print(json.dumps({"trial": trial_id, "stamp": w["Trial ID"], "status": w["Status"], "end_reason": w["End Reason"],
                          "trap": trap(data, r1_traps_a[0])["Status"], "open": len(open_windows(data, r1_traps_a[0]))}))
        """
    )
    assert out["stamp"] == out["trial"], "history stays tagged with the trial after the trap leaves it"
    assert out["status"] == "Closed" and out["end_reason"] == "Trap deactivated" and out["trap"] == "Inactive" and out["open"] == 0


def test_path_7_repair_missing_window_stamps_via_the_same_chokepoint() -> None:
    out = _run(
        """
        trial_id = app.create_trial(data, site_a, [LABEL_R1], when)
        t = r1_traps_a[0]
        data["Windows"] = data["Windows"][data["Windows"]["Trap ID"] != t].copy()
        data["Traps"].loc[data["Traps"]["Trap ID"] == t, "Deployment Start"] = "2026-08-20 08:00:00"
        window_id = app.repair_missing_window(data, t)
        reloaded = app.load_data()
        w = reloaded["Windows"].set_index("Window ID").loc[window_id]
        print(json.dumps({"trial": trial_id, "stamp": w["Trial ID"]}))
        """
    )
    assert out["stamp"] == out["trial"]


def test_rebuild_an_inactive_trap_then_activate_gives_exactly_one_open_window() -> None:
    out = _run(
        """
        app.create_trial(data, site_a, [LABEL_R1_OLD], when)
        stage_inactive(r1_traps_a[:1])
        app.change_trap_build(data, r1_traps_a[0], "R1", "R1 Build 4.2", when, "stage", commit=False)
        app.activate_trap(data, r1_traps_a[0], when, "start", commit=False)
        app.save_data(data)
        print(json.dumps({"open": len(open_windows(app.load_data(), r1_traps_a[0]))}))
        """
    )
    assert out == {"open": 1}


# --- derived Kills sheet --------------------------------------------------------

def test_the_derived_kills_sheet_carries_the_trial_id_of_the_kill() -> None:
    out = _run(
        """
        trial_id = app.create_trial(data, site_a, [LABEL_R1], when)
        stage_inactive(r1_traps_a[:1])
        app.activate_trap(data, r1_traps_a[0], when, "start", commit=False)
        window_id = open_windows(data, r1_traps_a[0]).iloc[0]["Window ID"]
        idx = data["Windows"].index[data["Windows"]["Window ID"] == window_id][0]
        data["Windows"].loc[idx, ["Status", "End Time", "Finding At Close", "Final Humane Kill"]] = ["Closed", "2026-09-02 09:00:00", "Dead animal found", "Pending"]
        app.save_data(data)
        kills = app.load_data()["Kills"]
        row = kills[kills["Window ID"] == window_id].iloc[0]
        print(json.dumps({"trial": trial_id, "kill_trial": row["Trial ID"], "columns": list(kills.columns)}))
        """
    )
    assert out["kill_trial"] == out["trial"]
    assert out["columns"][-1] == "Trial ID" and out["columns"][:-1] == [
        "Window ID", "Trap ID", "Site ID", "Build Version", "Kill Time", "Final Humane Kill",
        "Interaction To Kill Min", "Necropsy Assessment", "Animal Weight Range", "Bag ID",
    ]


# --- one guard, in one place ----------------------------------------------------

def _function_source(name: str) -> str:
    match = re.search(rf"^def {name}\(.*?(?=^def |^class |^[A-Za-z_]+ = )", APP_SOURCE, re.S | re.M)
    assert match, f"{name} not found"
    return match.group(0)


def test_the_activation_guard_lives_in_activate_trap_and_nowhere_else() -> None:
    """T3: no duplicated copies of the rule. Display-only copy elsewhere (the
    bulk expander's up-front message) calls the same message function."""
    assert APP_SOURCE.count("isn't part of") == 1, "the declared-build refusal text exists once"
    assert APP_SOURCE.count("Every active trap belongs to a trial") == 1, "the no-trial refusal text exists once"
    assert APP_SOURCE.count("raise ValueError(no_open_trial_message(") == 1, "the no-trial refusal is raised in exactly one place"
    guard = _function_source("activate_trap")
    assert "raise ValueError(no_open_trial_message(" in guard and "isn't part of" in guard
    for name in ("start_window", "deactivate_trap", "repair_missing_window", "move_trap", "site_trial_id_for_window"):
        body = _function_source(name)
        assert "no_open_trial_message" not in body and "isn't part of" not in body, f"{name} must not enforce T2"
    # start_window reaches the trial only through the never-raising helper.
    start = _function_source("start_window")
    assert "site_trial_id_for_window(" in start and "open_trial(" not in start
    # The only other callers of the message function are display-only.
    callers = [m.start() for m in re.finditer(r"no_open_trial_message\(", APP_SOURCE)]
    assert len(callers) == 3, "definition, the one raise, and the bulk expander's st.error"
