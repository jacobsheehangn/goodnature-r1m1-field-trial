"""Phase 2 (TRIAL_LIFECYCLE_BRIEF.md): Set up, Adopt and End as atomic, previewed actions.

Logic-level tests against the real app.py in a subprocess (see test_derived_sheets.py
for why). The screens are covered in test_trial_screens.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_COMMON = """
    import json, os, datetime as dt, app, pandas as pd
    D = dt.datetime
    data = app.create_sample_data()
    SITE, OTHER = "MAN", "KAI"
    T0 = D(2026, 9, 1, 8, 0)
    L43, L42, L41 = "R1 · R1 Build 4.3", "R1 · R1 Build 4.2", "R1 · R1 Build 4.1"
    data["Builds"] = pd.concat([data["Builds"], pd.DataFrame([["R1", "R1 Build 4.1", "Superseded", "2026-05-01", ""]], columns=data["Builds"].columns)], ignore_index=True)

    def traps_at(site, status=None, product=None):
        t = data["Traps"][data["Traps"]["Site ID"] == site]
        if status: t = t[t["Status"] == status]
        if product: t = t[t["Product"] == product]
        return t["Trap ID"].tolist()

    def stage_inactive(ids, when=T0):
        for t in ids:
            if app.trap_row(data, t)["Status"] == "Active":
                app.deactivate_trap(data, t, when, "stage", commit=False)

    def add_trap(trap_id, site, build="R1 Build 4.3", camera="", status="Inactive"):
        row = {c: "" for c in app.SHEETS["Traps"]}
        row.update({"Trap ID": trap_id, "Product": "R1", "Build Version": build, "Site ID": site, "Route Order": "50", "Location": "Spot " + trap_id,
                    "Camera ID": camera, "Status": status})
        data["Traps"] = pd.concat([data["Traps"], pd.DataFrame([row])], ignore_index=True)

    def add_window(trap_id, build, start, end, status="Closed", trial="", finding="Trap still set, no animal", site=None, camera="No"):
        t = app.trap_row(data, trap_id)
        row = {c: "" for c in app.SHEETS["Windows"]}
        row.update({"Window ID": f"W-{trap_id}-{start:%Y%m%d%H%M}", "Trap ID": trap_id, "Product": "R1", "Build Version": build, "Site ID": site or t["Site ID"],
                    "Camera Assigned": camera, "Start Time": app.dtstr(start), "End Time": app.dtstr(end) if end else "", "Status": status,
                    "Finding At Close": finding if status == "Closed" else "", "Final Humane Kill": "Pending", "Valid": "Pending", "Review Status": "Not required", "Trial ID": trial})
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([row])], ignore_index=True)
        return row["Window ID"]

    def wipe_windows(ids):
        data["Windows"] = data["Windows"][~data["Windows"]["Trap ID"].isin(ids)].copy()

    def open_count(d, trap_id):
        w = d["Windows"]; return int(((w["Trap ID"] == trap_id) & (w["Status"] == "Open")).sum())

    def trap(d, trap_id): return d["Traps"][d["Traps"]["Trap ID"] == trap_id].iloc[0]

    def attempt(fn, *a, **k):
        try:
            fn(*a, **k); return "ok"
        except ValueError as exc:
            return str(exc)

    def workbook_state():
        return {n: f.copy() for n, f in app.load_data().items()}
"""


class _Script(str):
    """A scenario fragment: `fragment + body` dedents each side on its own, so the two can be
    indented differently in this file."""

    def __add__(self, other):
        return _Script(textwrap.dedent(str(self)) + "\n" + textwrap.dedent(str(other)))


def _run(script: str, extra_env: dict | None = None) -> dict:
    env = os.environ.copy()
    env.update({"R1M1_ENVIRONMENT": "local", "R1M1_ALLOW_NO_AUTH": "true", "R1M1_SEED_MODE": "clean", "R1M1_DATA_DIR": tempfile.mkdtemp()})
    env.update(extra_env or {})
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_COMMON) + textwrap.dedent(script)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr[-3000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


# --- A: review statuses ---------------------------------------------------------------

def test_a_review_given_up_on_never_reads_as_complete() -> None:
    out = _run(
        """
        trap_id = traps_at(SITE)[0]
        wid = add_window(trap_id, "R1 Build 4.3", T0, T0 + dt.timedelta(days=1), finding="Dead animal found", camera="Yes")
        app.save_data(data)
        def followup(kind, status):
            app.add_followup(data, kind, SITE, trap_id, "V", wid, "B-1", "r", "d", "Normal")
            data["Followups"].loc[data["Followups"].index[-1], "Status"] = status
        followup("Camera review", "Complete")
        followup("Necropsy review", app.FOLLOWUP_UNRESOLVABLE)
        app.refresh_review_status(data, wid)
        w = lambda: data["Windows"][data["Windows"]["Window ID"] == wid].iloc[0]["Review Status"]
        results = {"unresolvable_and_complete": w()}
        data["Followups"].loc[data["Followups"]["Follow-up Type"] == "Necropsy review", "Status"] = "Open"
        app.refresh_review_status(data, wid); results["one_open"] = w()
        data["Followups"].loc[data["Followups"]["Follow-up Type"] == "Necropsy review", "Status"] = "Complete"
        app.refresh_review_status(data, wid); results["all_complete"] = w()
        data["Followups"].loc[data["Followups"]["Follow-up Type"] == "Necropsy review", "Status"] = app.FOLLOWUP_NO_CARCASS_STATUS
        app.refresh_review_status(data, wid); results["no_carcass_task"] = w()
        data["Followups"] = data["Followups"].iloc[0:0]
        app.refresh_review_status(data, wid); results["lost_tasks"] = w()
        print(json.dumps(results))
        """
    )
    assert out == {"unresolvable_and_complete": "Unresolved", "one_open": "Open", "all_complete": "Complete", "no_carcass_task": "Complete", "lost_tasks": "Needs recreation"}


# --- Set up ---------------------------------------------------------------------------

_SET_UP_SCENARIO = _Script("""
    # Trial A ran at SITE; its 5 traps were then ended. Two of them were left on an old build.
    r1 = traps_at(SITE, product="R1")
    wipe_windows(traps_at(SITE) + traps_at(OTHER))
    stage_inactive(traps_at(SITE))
    app.create_trial(data, SITE, [L43], T0)
    for t in r1: app.activate_trap(data, t, T0, "start A", commit=False)
    for t in r1: app.deactivate_trap(data, t, T0 + dt.timedelta(days=5), "end A", commit=False)
    data["Trials"].loc[data["Trials"]["Status"] == "Open", ["Status", "End Time"]] = ["Ended", app.dtstr(T0 + dt.timedelta(days=5))]
    for t in r1[3:]:
        app.change_trap_build(data, t, "R1", "R1 Build 4.1", T0 + dt.timedelta(days=6), "stage old build", commit=False)
    # two brand-new traps, two traps relocating in from another site
    add_trap("NEW-1", SITE); add_trap("NEW-2", SITE)
    moving = traps_at(OTHER, product="R1")[:2]
    stage_inactive(moving)
    app.save_data(data)
    data = app.load_data()
    EFFECTIVE = D(2026, 10, 1, 9, 0)
""")


def test_set_up_brings_a_mixed_roster_onto_the_right_builds_in_one_pass() -> None:
    out = _run(
        _SET_UP_SCENARIO
        + """
        pool = app.set_up_pool(data, SITE, product="R1")
        groups = {k: v["Trap ID"].tolist() for k, v in pool.items()}
        declared = [L43, L42]
        defaults = {t["Trap ID"]: app.set_up_default_build(t, declared) for _, t in pd.concat([pool["carried"], pool["new"]]).iterrows()}
        assignments = {t: (defaults.get(t) or (L42 if t in groups["carried"] else L43)) for t in groups["carried"] + groups["new"] + groups["relocated"]}
        audit_before = len(data["Audit Log"])
        result = app.commit_set_up(data, SITE, declared, EFFECTIVE, assignments, note="week one")
        reloaded = app.load_data()
        trial = app.open_trial(reloaded, SITE)
        rows = {}
        for t in assignments:
            tr = trap(reloaded, t)
            w = reloaded["Windows"][(reloaded["Windows"]["Trap ID"] == t) & (reloaded["Windows"]["Status"] == "Open")]
            rows[t] = {"site": tr["Site ID"], "status": tr["Status"], "build": app.trial_build_label(tr["Product"], tr["Build Version"]), "open": len(w),
                       "stamp": w.iloc[0]["Trial ID"] if len(w) else None, "deployment": bool(str(tr["Deployment Start"]).strip())}
        new_audit = reloaded["Audit Log"].iloc[audit_before:]
        print(json.dumps({"groups": groups, "defaults": defaults, "assignments": assignments, "rows": rows, "trial": trial["Trial ID"], "declared": trial["Declared Builds"],
                          "origin": trial["Origin"], "start": trial["Start Time"], "note": trial["Notes"], "ids_returned": len(result["change_ids"]),
                          "audit_added": len(new_audit), "audit_ids_match": set(result["change_ids"]) == set(new_audit["Change ID"]),
                          "audit_reasons": sorted(set(new_audit["Reason"])), "trial_audit": int((new_audit["Record Type"] == "Trial").sum())}))
        """
    )
    assert len(out["groups"]["carried"]) == 5 and len(out["groups"]["new"]) == 2 and len(out["groups"]["relocated"]) == 2
    # Carried over: three previous builds are declared (kept as the default); two are not ("Needs assignment").
    declared_defaults = [t for t in out["groups"]["carried"] if out["defaults"][t]]
    assert len(declared_defaults) == 3 and all(not out["defaults"][t] for t in out["groups"]["carried"] if t not in declared_defaults)
    assert out["trial"].startswith("TRIAL-MAN-02") and out["declared"] == "R1 · R1 Build 4.3; R1 · R1 Build 4.2" and out["origin"] == "Started"
    assert out["start"] == "2026-10-01 09:00:00" and out["note"] == "week one"
    for t, row in out["rows"].items():
        assert row["site"] == "MAN" and row["status"] == "Active" and row["build"] == out["assignments"][t], t
        assert row["open"] == 1 and row["stamp"] == out["trial"] and row["deployment"], t
    assert out["audit_added"] == out["ids_returned"] and out["audit_ids_match"]
    assert out["audit_reasons"] == ["Trial started at site"], "a fixed system reason, never typed"
    assert out["trial_audit"] == 1


def test_a_carried_over_trap_whose_build_is_not_declared_is_never_silently_defaulted() -> None:
    out = _run(
        _SET_UP_SCENARIO
        + """
        pool = app.set_up_pool(data, SITE, product="R1")
        old_build_traps = [t for _, t in pool["carried"].iterrows() if t["Build Version"] == "R1 Build 4.1"]
        print(json.dumps({"n": len(old_build_traps), "defaults": [app.set_up_default_build(t, [L43, L42]) for t in old_build_traps]}))
        """
    )
    assert out == {"n": 2, "defaults": ["", ""]}


def test_set_up_refuses_missing_builds_a_fourth_build_and_a_busy_site_and_writes_nothing() -> None:
    out = _run(
        _SET_UP_SCENARIO
        + """
        pool = app.set_up_pool(data, SITE, product="R1")
        ids = pool["carried"]["Trap ID"].tolist()[:2] + pool["new"]["Trap ID"].tolist()
        before = workbook_state()
        res = {}
        res["missing"] = attempt(app.commit_set_up, data, SITE, [L43, L42], EFFECTIVE, {ids[0]: L43, ids[1]: "", ids[2]: ""})
        res["fourth_build"] = attempt(app.commit_set_up, data, SITE, [L43, L42, L41, "R1 · R1 Build 9"], EFFECTIVE, {ids[0]: L43})
        res["mixed_product"] = attempt(app.commit_set_up, data, SITE, [L43, "M1 · M1 Build 3.7"], EFFECTIVE, {ids[0]: L43})
        res["no_traps"] = attempt(app.commit_set_up, data, SITE, [L43], EFFECTIVE, {})
        res["wrong_product_trap"] = attempt(app.commit_set_up, data, SITE, [L43], EFFECTIVE, {"M1-MAN-004": L43})
        res["active_elsewhere"] = attempt(app.commit_set_up, data, SITE, [L43], EFFECTIVE, {traps_at("WAI", "Active", "R1")[0]: L43})
        after_refusals = workbook_state()
        res["refusals_changed_nothing"] = all(before[n].equals(after_refusals[n]) for n in before) and all(before[n].equals(data[n]) for n in before)
        app.commit_set_up(data, SITE, [L43], EFFECTIVE, {ids[0]: L43})
        res["busy_site"] = attempt(app.commit_set_up, data, SITE, [L43], EFFECTIVE, {ids[1]: L43})
        print(json.dumps(res))
        """
    )
    assert out["missing"].startswith("2 traps need a build before you can continue: ")
    assert "1 to 3" in out["fourth_build"] and "same product" in out["mixed_product"]
    assert out["no_traps"] == "Choose at least one trap."
    assert out["wrong_product_trap"].startswith("Not available for this trial") and out["active_elsewhere"].startswith("Not available for this trial")
    assert out["busy_site"] == "This site already has a trial running."
    assert out["refusals_changed_nothing"], "every refusal leaves the workbook, on disk and in memory, as it was"


def test_a_failure_part_way_through_set_up_leaves_the_workbook_exactly_as_it_was() -> None:
    script = (
        _SET_UP_SCENARIO
        + """
        pool = app.set_up_pool(data, SITE, product="R1")
        ids = pool["new"]["Trap ID"].tolist() + pool["relocated"]["Trap ID"].tolist()
        before_bytes = app.DATA_FILE.read_bytes(); before_mtime = app.DATA_FILE.stat().st_mtime_ns
        in_memory_before = {n: f.copy() for n, f in data.items()}
        raised = ""
        try:
            app.commit_set_up(data, SITE, [L43], EFFECTIVE, {t: L43 for t in ids})
        except RuntimeError as exc:
            raised = str(exc)
        print(json.dumps({"raised": raised, "file_unchanged": app.DATA_FILE.read_bytes() == before_bytes and app.DATA_FILE.stat().st_mtime_ns == before_mtime,
                          "memory_unchanged": all(in_memory_before[n].equals(data[n]) for n in data), "trials": len(app.load_data()["Trials"])}))
        """
    )
    out = _run(script, {"R1M1_TEST_FAIL_TRIAL_ACTION": "set_up:2"})
    assert out["raised"].startswith("forced failure in set_up at step 2")
    assert out["file_unchanged"] and out["memory_unchanged"], "never half a trial"
    assert out["trials"] == 1, "only trial A (already there) exists"


# --- Adopt ----------------------------------------------------------------------------

_ADOPT_SCENARIO = _Script("""
    # OTHER runs untracked: 3 active R1 traps on two builds, with a history that includes an older build.
    stage_inactive(traps_at(OTHER, product="M1"))
    act = traps_at(OTHER, "Active", "R1")[:3]
    stage_inactive(traps_at(OTHER, "Active", "R1")[3:])
    a, b, c = act
    app.change_trap_build(data, c, "R1", "R1 Build 4.2", T0 - dt.timedelta(days=30), "history", commit=False)
    # wipe the sample windows for these traps and write an explicit history
    data["Windows"] = data["Windows"][~data["Windows"]["Trap ID"].isin(act)].copy()
    h = {}
    h["a_old"] = add_window(a, "R1 Build 4.2", D(2026, 8, 1, 8), D(2026, 8, 8, 8))          # older build: untagged
    h["a1"] = add_window(a, "R1 Build 4.3", D(2026, 8, 8, 8), D(2026, 8, 15, 8))           # current build, trial start
    h["a2"] = add_window(a, "R1 Build 4.3", D(2026, 8, 15, 8), D(2026, 8, 22, 8))
    h["a_open"] = add_window(a, "R1 Build 4.3", D(2026, 8, 22, 8), None, status="Open")
    h["b1"] = add_window(b, "R1 Build 4.3", D(2026, 8, 10, 8), D(2026, 8, 17, 8))
    h["b_open"] = add_window(b, "R1 Build 4.3", D(2026, 8, 17, 8), None, status="Open")
    h["c1"] = add_window(c, "R1 Build 4.2", D(2026, 8, 12, 8), D(2026, 8, 19, 8))
    h["c_open"] = add_window(c, "R1 Build 4.2", D(2026, 8, 19, 8), None, status="Open")
    h["elsewhere"] = add_window(traps_at("WAI")[0], "R1 Build 4.3", D(2026, 8, 20, 8), D(2026, 8, 25, 8))
    data["Traps"].loc[data["Traps"]["Trap ID"] == c, ["Product", "Build Version"]] = ["R1", "R1 Build 4.2"]
    data["Traps"].loc[data["Traps"]["Trap ID"].isin([a, b]), ["Product", "Build Version"]] = ["R1", "R1 Build 4.3"]
    app.save_data(data)
    data = app.load_data()
""")


def test_adoption_tags_only_current_build_windows_from_the_trial_start_onward() -> None:
    out = _run(
        _ADOPT_SCENARIO
        + """
        plan = app.adoption_plan(data, OTHER)
        before = workbook_state()
        result = app.commit_adoption(data, OTHER, plan["start_time"], note="adopted")
        after = app.load_data()
        w = after["Windows"].set_index("Window ID")
        tagged = sorted(w.index[w["Trial ID"] != ""])
        trial = app.open_trial(after, OTHER)
        # nothing else in the workbook changed except the new trial, the Trial ID column and the audit rows
        w_before = before["Windows"].set_index("Window ID")
        other_cols = [c for c in w.columns if c != "Trial ID"]
        print(json.dumps({"builds": plan["builds"], "default_start": app.dtstr(plan["default_start"]), "to_tag": plan["windows_to_tag"], "traps_with_tags": plan["traps_with_tags"],
            "untagged": plan["windows_left_untagged"], "audit_planned": plan["audit_entries"], "plan_ids": sorted(plan["tag_window_ids"]), "tagged": tagged, "h": h,
            "trial": trial["Trial ID"], "origin": trial["Origin"], "start": trial["Start Time"], "declared": trial["Declared Builds"], "result": [result["windows_tagged"], result["traps_tagged"]],
            "other_columns_identical": w_before[other_cols].equals(w[other_cols]), "traps_identical": before["Traps"].equals(after["Traps"]),
            "audit_added": len(after["Audit Log"]) - len(before["Audit Log"]), "ids_returned": len(result["change_ids"]),
            "adopt_audit": after["Audit Log"].iloc[len(before["Audit Log"]):][["Record Type", "Field", "Reason"]].values.tolist()}))
        """
    )
    h = out["h"]
    assert out["builds"] == [["R1 · R1 Build 4.2", 1], ["R1 · R1 Build 4.3", 2]]
    assert out["default_start"] == "2026-08-08 08:00:00", "when the current builds began at this site, not now"
    in_scope = sorted(h[k] for k in ("a1", "a2", "a_open", "b1", "b_open", "c1", "c_open"))
    assert out["tagged"] == in_scope == out["plan_ids"], "only current-build windows from the start onward"
    for k in ("a_old", "elsewhere"):
        assert h[k] not in out["tagged"]
    assert out["to_tag"] == 7 and out["traps_with_tags"] == 3 and out["result"] == [7, 3]
    assert out["origin"] == "Adopted" and out["start"] == "2026-08-08 08:00:00" and out["declared"] == "R1 · R1 Build 4.2; R1 · R1 Build 4.3"
    assert out["other_columns_identical"] and out["traps_identical"], "adoption is a metadata stamp; nothing else changes"
    assert out["audit_added"] == out["ids_returned"] == 4 and ["Trap", "Windows tagged to trial", "Adopted into trial"] in out["adopt_audit"]


def test_adoption_is_refused_for_an_open_trial_more_than_three_builds_mixed_products_and_an_empty_site() -> None:
    out = _run(
        _ADOPT_SCENARIO
        + """
        res = {}
        res["empty_site"] = attempt(app.adoption_plan, data, "WAI") if not traps_at("WAI", "Active") else "skipped"
        stage_inactive(traps_at("WAI", "Active"))
        res["no_active_traps"] = attempt(app.adoption_plan, data, "WAI")
        # more than three builds
        for i, t in enumerate(act): pass
        for build, tid in zip(["R1 Build 4.1", "R1 Build 4.3", "R1 Build 4.2"], act): data["Traps"].loc[data["Traps"]["Trap ID"] == tid, "Build Version"] = build
        add_trap("X-4", OTHER, build="R1 Build 9.9", status="Active")
        data["Builds"] = pd.concat([data["Builds"], pd.DataFrame([["R1", "R1 Build 9.9", "Current", "2026-09-01", ""]], columns=data["Builds"].columns)], ignore_index=True)
        res["four_builds"] = attempt(app.adoption_plan, data, OTHER)
        data["Traps"] = data["Traps"][data["Traps"]["Trap ID"] != "X-4"]
        # mixed products
        data["Traps"].loc[data["Traps"]["Trap ID"] == act[0], ["Product", "Build Version"]] = ["M1", "M1 Build 3.7"]
        res["mixed"] = attempt(app.adoption_plan, data, OTHER)
        data["Traps"].loc[data["Traps"]["Trap ID"] == act[0], ["Product", "Build Version"]] = ["R1", "R1 Build 4.3"]
        app.create_trial(data, OTHER, [L43], T0)
        res["has_trial"] = attempt(app.adoption_plan, data, OTHER)
        print(json.dumps(res))
        """
    )
    assert out["no_active_traps"] == "There are no active traps at this site to track."
    assert "4 builds are running here" in out["four_builds"]
    assert out["mixed"].startswith("This site runs more than one product.")
    assert out["has_trial"] == "This site already has a trial running."


def test_adoption_classifies_active_traps_with_no_open_window_without_blocking() -> None:
    out = _run(
        _ADOPT_SCENARIO
        + """
        a, b, c = act
        # a: awaiting service (open Trap not ready follow-up), b: a defect (no window, no follow-up), c keeps its open window.
        for t in (a, b):
            data["Windows"].loc[(data["Windows"]["Trap ID"] == t) & (data["Windows"]["Status"] == "Open"), ["Status", "End Time"]] = ["Closed", app.dtstr(D(2026, 9, 1, 8))]
        app.add_followup(data, "Trap not ready", OTHER, a, "V", "W", "", "r", "d", "High")
        windowless = app.adoption_plan(data, OTHER)["windowless"]
        print(json.dumps({"windowless": windowless, "a": a, "b": b, "plan_ok": True}))
        """
    )
    assert out["windowless"] == {"awaiting_service": [out["a"]], "trap_missing": [], "defect": [out["b"]]}


# --- End trial ------------------------------------------------------------------------

_END_SCENARIO = _Script("""
    # A 5-trap trial at SITE, on test data: two traps have cameras.
    r1 = traps_at(SITE, product="R1")
    wipe_windows(traps_at(SITE))
    stage_inactive(traps_at(SITE))
    for t in (r1[0], r1[3]): data["Traps"].loc[data["Traps"]["Trap ID"] == t, "Camera ID"] = "CAM-" + t[-3:]   # r1[3] is unchecked and has a camera
    app.create_trial(data, SITE, [L43], T0)
    for t in r1: app.activate_trap(data, t, T0, "start", commit=False)
    TRIAL = app.open_trial(data, SITE)["Trial ID"]
    # evidence: a camera review and a necropsy review on a dead-animal window, plus two hardware tasks
    t_kill = r1[0]
    kill_w = add_window(t_kill, "R1 Build 4.3", T0, T0 + dt.timedelta(days=2), finding="Dead animal found", camera="Yes", trial=TRIAL)
    data["Windows"].loc[data["Windows"]["Window ID"] == kill_w, ["Species", "Bag ID", "Review Status"]] = ["Rat", "MAN-001", "Open"]
    app.add_followup(data, "Camera review", SITE, t_kill, "V0", kill_w, "MAN-001", "Dead animal found", "d", "Normal")
    app.add_followup(data, "Necropsy review", SITE, t_kill, "V0", kill_w, "MAN-001", "Dead animal collected", "d", "Normal")
    app.add_followup(data, "Trap not ready", SITE, r1[2], "V0", "W", "", "r", "d", "High")
    app.add_followup(data, "Camera issue", SITE, r1[1], "V0", "W", "", "r", "d", "High")
    # a visit in progress with only some traps checked
    vid = "VIS-TEST-1"
    data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([[vid, SITE, "Op", app.dtstr(D(2026, 9, 5, 8)), "", "In progress", ""]], columns=app.SHEETS["Visits"])], ignore_index=True)
    for t in r1[:3]:
        row = {c: "" for c in app.SHEETS["Checks"]}; row.update({"Check ID": "C-" + t, "Visit ID": vid, "Trap ID": t, "Check Time": app.dtstr(D(2026, 9, 5, 9)), "Finding": "Trap still set, no animal"})
        data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([row])], ignore_index=True)
    app.save_data(data)
    data = app.load_data()
    END = D(2026, 9, 5, 12, 0)
    nec = data["Followups"][data["Followups"]["Follow-up Type"] == "Necropsy review"].iloc[0]["Follow-up ID"]
    cam = data["Followups"][data["Followups"]["Follow-up Type"] == "Camera review"].iloc[0]["Follow-up ID"]
""")


def test_end_trial_is_blocked_until_every_evidence_review_has_a_decision() -> None:
    out = _run(
        _END_SCENARIO
        + """
        res = {}
        res["no_decisions"] = attempt(app.plan_trial_end, data, SITE, END, (), vid)
        res["one_decision"] = attempt(app.plan_trial_end, data, SITE, END, (nec,), vid)
        res["both"] = attempt(app.plan_trial_end, data, SITE, END, (nec, cam), vid)
        res["mid_visit_without_visit_id"] = attempt(app.plan_trial_end, data, SITE, END, (nec, cam), "")
        gate = app.trial_end_gate(data, SITE)
        res["gate_types"] = sorted(gate["evidence"]["Follow-up Type"].tolist()); res["hardware_types"] = sorted(gate["hardware"]["Follow-up Type"].tolist())
        res["evidence_trial_id"] = sorted(set(gate["evidence"]["Trial ID"]))
        print(json.dumps(res))
        """
    )
    assert out["no_decisions"] == "2 evidence reviews still need a decision before this trial can end."
    assert out["one_decision"] == "1 evidence review still needs a decision before this trial can end."
    assert out["both"] == "ok"
    assert out["mid_visit_without_visit_id"].startswith("A visit is in progress.")
    assert out["gate_types"] == ["Camera review", "Necropsy review"] and out["hardware_types"] == ["Camera issue", "Trap not ready"]
    assert out["evidence_trial_id"] and out["evidence_trial_id"][0].startswith("TRIAL-MAN-")


def test_end_trial_resolves_everything_in_one_atomic_save_and_audits_every_field() -> None:
    out = _run(
        _END_SCENARIO
        + """
        r1_now = traps_at(SITE, "Active")
        before = workbook_state()
        unchecked = app.not_checked_this_visit(data, SITE, vid)
        camera_traps = unchecked[unchecked["Has camera"]]["Trap ID"].tolist()
        res = app.commit_trial_end(data, SITE, END, unresolvable_ids=(nec, cam), visit_id=vid, final_period_traps=camera_traps[:1], note="done")
        after = app.load_data()
        f = after["Followups"].set_index("Follow-up ID")
        w = after["Windows"].set_index("Window ID")
        v = after["Visits"][after["Visits"]["Visit ID"] == vid].iloc[0]
        trial = after["Trials"][after["Trials"]["Trial ID"] == TRIAL].iloc[0]
        new_fu = after["Followups"][~after["Followups"]["Follow-up ID"].isin(before["Followups"]["Follow-up ID"])]
        audit_new = after["Audit Log"].iloc[len(before["Audit Log"]):]
        print(json.dumps({
            "unchecked": unchecked["Trap ID"].tolist(), "camera_unchecked": camera_traps, "res": {k: res[k] for k in res if k != "change_ids"},
            "traps": sorted(set(after["Traps"][after["Traps"]["Site ID"] == SITE]["Status"])), "open_windows": int(((after["Windows"]["Site ID"] == SITE) & (after["Windows"]["Status"] == "Open")).sum()),
            "nec": [f.loc[nec, "Status"], f.loc[nec, "Completed Time"]], "cam": f.loc[cam, "Status"],
            "hardware": sorted(f[f["Follow-up Type"].isin(app.HARDWARE_TASK_TYPES)]["Status"]),
            "kill_final": w.loc[kill_w, "Final Humane Kill"], "kill_review": w.loc[kill_w, "Review Status"],
            "visit": [v["Status"], v["End Time"], v["Notes"]], "trial": [trial["Status"], trial["End Time"], trial["Notes"]],
            "new_followups": new_fu[["Follow-up Type", "Status", "Reason", "Trap ID"]].values.tolist(),
            "final_period_window_review": w.loc[new_fu.iloc[0]["Window ID"], "Review Status"] if len(new_fu) else None,
            "ids": len(res["change_ids"]), "audit_added": len(audit_new), "ids_match": set(res["change_ids"]) == set(audit_new["Change ID"]),
            "audit_fields": sorted({(r["Record Type"], r["Field"]) for _, r in audit_new.iterrows()}),
            "audit_reasons": sorted(set(audit_new["Reason"])),
            "next_due_uses_completed_only": app.latest_completed_visit(after, SITE) is None,
            "active_visit_now": app.active_visit(after, SITE) is None, "open_trial_now": app.open_trial(after, SITE) is None,
            "trial_perf_awaiting": int((~after["Windows"][after["Windows"]["Finding At Close"] == "Dead animal found"]["Final Humane Kill"].isin(["Yes", "No"]) & ~app.not_assessed_mask(after["Windows"][after["Windows"]["Finding At Close"] == "Dead animal found"]["Final Humane Kill"])).sum()),
        }))
        """
    )
    assert out["traps"] == ["Inactive"] and out["open_windows"] == 0
    assert out["nec"][0] == "Unresolvable — trial ended before review" and out["cam"] == "Unresolvable — trial ended before review"
    assert out["nec"][0] != "Complete"
    assert out["hardware"] == ["Resolved — removed at trial end"] * 2, "hardware tasks get their own status, never Complete"
    assert out["kill_final"] == "Not assessed — trial ended" and out["kill_review"] == "Unresolved"
    assert out["visit"][0] == "Partial" and out["visit"][1] == "2026-09-05 12:00:00" and out["visit"][2] == "Partial: 3 of 5 traps checked at trial end"
    assert out["trial"][:2] == ["Ended", "2026-09-05 12:00:00"] and out["trial"][2].endswith("done")
    assert len(out["new_followups"]) == 1 and out["new_followups"][0][:3] == ["Camera review", "Open", "Final period — trial ended"]
    assert out["final_period_window_review"] == "Open", "a final-period review keeps its window's review Open, not Not required"
    assert out["res"]["traps_deactivated"] == 5 and out["res"]["hardware_resolved"] == 2 and out["res"]["unresolvable"] == 2
    assert out["res"]["visit_status"] == "Partial" and out["res"]["final_period_reviews"] == 1
    assert out["ids"] == out["audit_added"] and out["ids_match"]
    assert ["Follow-up", "Status"] in [list(x) for x in out["audit_fields"]] and ["Visit", "Status"] in [list(x) for x in out["audit_fields"]]
    assert ["Window", "End Time"] in [list(x) for x in out["audit_fields"]] and ["Trial", "Status"] in [list(x) for x in out["audit_fields"]]
    assert out["audit_reasons"] == sorted({"Trial ended at site", "Final period — trial ended"})
    assert out["next_due_uses_completed_only"], "a Partial visit is not a completed visit, so Next due is not reset"
    assert out["active_visit_now"] and out["open_trial_now"]
    assert out["trial_perf_awaiting"] == 0, "the kill no longer sits in 'awaiting final assessment'"


def test_a_fully_checked_visit_closes_as_complete_and_unticked_or_no_camera_traps_queue_nothing() -> None:
    out = _run(
        _END_SCENARIO
        + """
        for t in traps_at(SITE, "Active")[3:]:
            row = {c: "" for c in app.SHEETS["Checks"]}; row.update({"Check ID": "C-" + t, "Visit ID": vid, "Trap ID": t, "Check Time": app.dtstr(D(2026, 9, 5, 10)), "Finding": "Trap still set, no animal"})
            data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([row])], ignore_index=True)
        res = app.commit_trial_end(data, SITE, END, unresolvable_ids=(nec, cam), visit_id=vid)
        after = app.load_data()
        v = after["Visits"][after["Visits"]["Visit ID"] == vid].iloc[0]
        print(json.dumps({"status": v["Status"], "notes": v["Notes"], "final_period": res["final_period_reviews"], "latest_completed": str(app.latest_completed_visit(after, SITE)["Visit ID"])}))
        """
    )
    assert out == {"status": "Complete", "notes": "", "final_period": 0, "latest_completed": "VIS-TEST-1"}


def test_final_period_reviews_can_only_be_queued_for_unchecked_camera_traps() -> None:
    out = _run(
        _END_SCENARIO
        + """
        unchecked = app.not_checked_this_visit(data, SITE, vid)
        no_camera = unchecked[~unchecked["Has camera"]]["Trap ID"].tolist()
        checked = traps_at(SITE, "Active")[0]
        print(json.dumps({"no_camera_trap": attempt(app.plan_trial_end, data, SITE, END, (nec, cam), vid, (no_camera[0],)),
                          "checked_trap": attempt(app.plan_trial_end, data, SITE, END, (nec, cam), vid, (checked,)),
                          "last_checked": [str(x) for x in unchecked["Last checked"]]}))
        """
    )
    assert out["no_camera_trap"].startswith("A final-period camera review can only be queued for an unchecked trap with a camera")
    assert out["checked_trap"].startswith("A final-period camera review can only be queued")
    assert all(x.startswith("2026-09-05") or x == "None" for x in out["last_checked"]), "each unchecked trap shows its last-checked time"


def test_a_failure_part_way_through_end_trial_leaves_the_workbook_exactly_as_it_was() -> None:
    script = (
        _END_SCENARIO
        + """
        before_bytes = app.DATA_FILE.read_bytes(); before_mtime = app.DATA_FILE.stat().st_mtime_ns
        in_memory_before = {n: f.copy() for n, f in data.items()}
        raised = ""
        try:
            app.commit_trial_end(data, SITE, END, unresolvable_ids=(nec, cam), visit_id=vid)
        except RuntimeError as exc:
            raised = str(exc)
        reloaded = app.load_data()
        print(json.dumps({"raised": raised, "file_unchanged": app.DATA_FILE.read_bytes() == before_bytes and app.DATA_FILE.stat().st_mtime_ns == before_mtime,
                          "memory_unchanged": all(in_memory_before[n].equals(data[n]) for n in data),
                          "trial_still_open": app.open_trial(reloaded, SITE) is not None, "traps_active": len(traps_at(SITE, "Active"))}))
        """
    )
    for step in ("4", "8"):
        out = _run(script, {"R1M1_TEST_FAIL_TRIAL_ACTION": f"end:{step}"})
        assert out["raised"].startswith("forced failure in end at step"), step
        assert out["file_unchanged"] and out["memory_unchanged"] and out["trial_still_open"] and out["traps_active"] == 5, step


def test_partial_is_not_in_progress_and_not_a_completed_visit_for_any_reader() -> None:
    out = _run(
        """
        site_id = SITE
        row = ["VIS-P", site_id, "Op", app.dtstr(D(2026, 9, 5, 8)), app.dtstr(D(2026, 9, 5, 12)), "Partial", "Partial: 3 of 5 traps checked at trial end"]
        data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([row], columns=app.SHEETS["Visits"])], ignore_index=True)
        done = ["VIS-C", site_id, "Op", app.dtstr(D(2026, 9, 1, 8)), app.dtstr(D(2026, 9, 1, 12)), "Complete", ""]
        data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([done], columns=app.SHEETS["Visits"])], ignore_index=True)
        print(json.dumps({"active_visit": app.active_visit(data, site_id) is None, "latest_completed": str(app.latest_completed_visit(data, site_id)["Visit ID"]),
                          "resume_candidate": app.validate_workflow_resume(data, site_id, "VIS-P", traps_at(site_id)[0]) is None,
                          "abandon_refused": attempt(app.abandon_incomplete_visit, data, "VIS-P", "x")}))
        """
    )
    assert out["active_visit"] and out["latest_completed"] == "VIS-C" and out["resume_candidate"]
    assert out["abandon_refused"] != "ok", "a Partial visit is finished history, not an open visit to abandon"


# --- the hub's derived values ---------------------------------------------------------

def test_hub_values_are_derived_from_data_including_an_adopted_trial() -> None:
    out = _run(
        _END_SCENARIO
        + """
        trial = app.open_trial(data, SITE)
        # two finished visits in the trial (one Partial) and one earlier than the trial start
        def visit(vid_, start, status, traps_checked, notes=""):
            data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([[vid_, SITE, "Op", app.dtstr(start), app.dtstr(start + dt.timedelta(hours=3)), status, notes]], columns=app.SHEETS["Visits"])], ignore_index=True)
            for t in traps_at(SITE, "Active")[:traps_checked]:
                row = {c: "" for c in app.SHEETS["Checks"]}; row.update({"Check ID": f"C-{vid_}-{t}", "Visit ID": vid_, "Trap ID": t, "Check Time": app.dtstr(start)})
                data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([row])], ignore_index=True)
        visit("V-early", D(2026, 8, 20, 8), "Complete", 5)
        visit("V-1", D(2026, 9, 2, 8), "Complete", 5)
        visit("V-2", D(2026, 9, 3, 8), "Partial", 3, "Partial: 3 of 5 traps checked at trial end")
        s = app.trial_hub_summary(data, trial)
        print(json.dumps({"day": s["day"], "chips": s["chips"], "completed": s["completed_count"], "partial": len(s["partial"]), "last_traps": s["last_traps_checked"],
                          "last": app.dtstr(s["last_date"]), "open_followups": s["open_followups"], "necropsy": s["necropsy_open"], "camera": s["camera_open"],
                          "in_progress": s["in_progress_visit"] is not None}))
        """
    )
    assert out["chips"] == [["R1 · R1 Build 4.3", 5]] and out["completed"] == 1 and out["partial"] == 1
    assert out["last_traps"] == 5 and out["last"].startswith("2026-09-02")
    assert out["open_followups"] == 4, "camera review + necropsy review + trap not ready + camera issue, counted site-wide"
    assert out["necropsy"] == 1 and out["camera"] == 1 and out["in_progress"] is True
