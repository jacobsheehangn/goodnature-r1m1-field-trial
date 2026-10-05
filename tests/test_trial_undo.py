"""Phase 3 (TRIAL_LIFECYCLE_BRIEF.md): Undo for Set up, Track as a trial and End trial.

Each is undone from the action's own audit entries (by Change ID), never a snapshot: every affected
row returns to its exact prior state, and anything saved by an unrelated action in between survives."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_trial_lifecycle import _ADOPT_SCENARIO, _END_SCENARIO, _SET_UP_SCENARIO, _run  # noqa: E402

# The unrelated change saved between the action and its Undo, and the comparison helpers.
_COMPARE = """
    UNRELATED = traps_at("WAI")[0]
    def unrelated_save():
        d = app.load_data()
        d["Traps"].loc[d["Traps"]["Trap ID"] == UNRELATED, "Notes"] = "edited by someone else"
        app.save_data(d)
    def same(before, after, ignore=()):
        out = {}
        for name in before:
            if name == "Audit Log" or name in ("Trial Config", "Kills"):
                continue
            a = before[name].copy().reset_index(drop=True); b = after[name].copy().reset_index(drop=True)
            if name == "Traps":
                a.loc[a["Trap ID"] == UNRELATED, "Notes"] = "edited by someone else"
            out[name] = bool(a.equals(b))
        return out
    def audit_prefix_intact(before, after):
        n = len(before["Audit Log"])
        return before["Audit Log"].reset_index(drop=True).equals(after["Audit Log"].iloc[:n].reset_index(drop=True))
"""


def test_undo_set_up_puts_every_row_back_and_keeps_an_unrelated_save() -> None:
    out = _run(
        _SET_UP_SCENARIO
        + _COMPARE
        + """
        pool = app.set_up_pool(data, SITE, product="R1")
        ids = pool["carried"]["Trap ID"].tolist() + pool["new"]["Trap ID"].tolist() + pool["relocated"]["Trap ID"].tolist()[:2]
        assign = {t: (L43 if t in pool["new"]["Trap ID"].tolist() or t in pool["relocated"]["Trap ID"].tolist() else L42) for t in ids}
        before = workbook_state()
        result = app.commit_set_up(data, SITE, [L43, L42], EFFECTIVE, assign)
        unrelated_save()
        data = app.load_data()
        undo = app.undo_trial_action(data, "set_up", result["trial_id"], result["change_ids"])
        after = workbook_state()
        new_audit = after["Audit Log"].iloc[len(before["Audit Log"]):]
        print(json.dumps({"same": same(before, after), "audit_prefix": audit_prefix_intact(before, after), "undo": undo, "result_traps": result["trap_count"],
                          "undo_reasons": sorted({r.split(":")[0] for r in new_audit[new_audit["Reason"].str.startswith("Undo")]["Reason"]}),
                          "audit_entries_after_original": int(len(new_audit)), "open_trial": app.open_trial(after, SITE) is None,
                          "unrelated_kept": after["Traps"][after["Traps"]["Trap ID"] == UNRELATED].iloc[0]["Notes"]}))
        """
    )
    assert all(out["same"].values()), out["same"]
    assert out["audit_prefix"], "the Audit Log is only ever added to"
    assert out["undo"]["windows_removed"] == out["result_traps"] and out["undo"]["kind"] == "set_up"
    assert out["open_trial"] and out["unrelated_kept"] == "edited by someone else"
    assert out["undo_reasons"] == ["Undo"] and out["audit_entries_after_original"] > out["undo"]["entries_reversed"]


def test_undo_adopt_puts_every_row_back_and_keeps_an_unrelated_save() -> None:
    out = _run(
        _ADOPT_SCENARIO
        + _COMPARE
        + """
        plan = app.adoption_plan(data, OTHER)
        before = workbook_state()
        result = app.commit_adoption(data, OTHER, plan["start_time"])
        unrelated_save()
        data = app.load_data()
        undo = app.undo_trial_action(data, "adopt", result["trial_id"], result["change_ids"])
        after = workbook_state()
        print(json.dumps({"same": same(before, after), "audit_prefix": audit_prefix_intact(before, after), "undo": undo, "tagged": result["windows_tagged"],
                          "stamps_left": int((after["Windows"]["Trial ID"] != "").sum()), "trial_gone": app.open_trial(after, OTHER) is None}))
        """
    )
    assert all(out["same"].values()), out["same"]
    assert out["audit_prefix"] and out["trial_gone"] and out["stamps_left"] == 0
    assert out["undo"]["windows_unstamped"] == out["tagged"] and out["undo"]["windows_removed"] == 0


def test_undo_end_trial_restores_traps_windows_follow_ups_visit_and_trial() -> None:
    out = _run(
        _END_SCENARIO
        + _COMPARE
        + """
        unchecked = app.not_checked_this_visit(data, SITE, vid)
        camera_traps = unchecked[unchecked["Has camera"]]["Trap ID"].tolist()
        before = workbook_state()
        result = app.commit_trial_end(data, SITE, END, unresolvable_ids=(nec, cam), visit_id=vid, final_period_traps=camera_traps[:1], note="done")
        mid = workbook_state()
        unrelated_save()
        data = app.load_data()
        undo = app.undo_trial_action(data, "end", result["trial_id"], result["change_ids"])
        after = workbook_state()
        f = after["Followups"].set_index("Follow-up ID")
        print(json.dumps({"same": same(before, after), "audit_prefix": audit_prefix_intact(before, after), "undo": undo,
                          "was_ended": mid["Trials"].iloc[0]["Status"], "now": after["Trials"].iloc[0]["Status"], "end_time": after["Trials"].iloc[0]["End Time"],
                          "active_traps": len(traps_at(SITE, "Active")), "open_windows": int(((after["Windows"]["Site ID"] == SITE) & (after["Windows"]["Status"] == "Open")).sum()),
                          "followup_statuses": sorted(f["Status"]), "final_period_gone": len(after["Followups"]) == len(before["Followups"]),
                          "visit": after["Visits"][after["Visits"]["Visit ID"] == vid].iloc[0][["Status", "End Time", "Notes"]].tolist(),
                          "kill": after["Windows"][after["Windows"]["Window ID"] == kill_w].iloc[0][["Final Humane Kill", "Review Status"]].tolist()}))
        """
    )
    assert all(out["same"].values()), out["same"]
    assert out["audit_prefix"] and out["was_ended"] == "Ended" and out["now"] == "Open" and out["end_time"] == ""
    assert out["active_traps"] == 5 and out["open_windows"] == 5 and out["final_period_gone"]
    assert out["visit"] == ["In progress", "", ""] and out["kill"] == ["Pending", "Open"]
    assert out["followup_statuses"] == ["Open"] * 4


def test_undo_refuses_when_the_world_has_moved_on_and_writes_nothing() -> None:
    out = _run(
        _END_SCENARIO
        + _COMPARE
        + """
        res = {}
        done = app.commit_trial_end(data, SITE, END, unresolvable_ids=(nec, cam), visit_id=vid)
        # someone re-activated a trap after the trial ended (a new trial would be needed first, so just flip it)
        data = app.load_data()
        victim = traps_at(SITE)[0]
        data["Traps"].loc[data["Traps"]["Trap ID"] == victim, "Status"] = "Active"
        app.save_data(data)
        state = workbook_state()
        res["end_after_trap_changed"] = attempt(app.undo_trial_action, app.load_data(), "end", done["trial_id"], done["change_ids"])
        res["unchanged"] = all(state[n].equals(app.load_data()[n]) for n in state)
        # a bogus or repeated Change ID list
        res["unknown_ids"] = attempt(app.undo_trial_action, app.load_data(), "end", done["trial_id"], ["CHG-NOPE"])
        res["wrong_kind"] = attempt(app.undo_trial_action, app.load_data(), "nope", done["trial_id"], done["change_ids"])
        print(json.dumps(res))
        """
    )
    assert out["end_after_trap_changed"].startswith("Undo isn't possible any more:") and "status has changed since" in out["end_after_trap_changed"]
    assert out["unchanged"]
    assert out["unknown_ids"].startswith("Undo isn't possible any more: this action's record could not be found.")
    assert out["wrong_kind"] == "Unknown action."


def test_undo_set_up_is_refused_once_a_check_hangs_off_one_of_its_windows_and_twice_is_refused() -> None:
    out = _run(
        _SET_UP_SCENARIO
        + """
        pool = app.set_up_pool(data, SITE, product="R1")
        ids = pool["new"]["Trap ID"].tolist()
        result = app.commit_set_up(data, SITE, [L43], EFFECTIVE, {t: L43 for t in ids})
        data = app.load_data()
        w = data["Windows"][data["Windows"]["Trial ID"] == result["trial_id"]].iloc[0]
        row = {c: "" for c in app.SHEETS["Checks"]}
        row.update({"Check ID": "C-LATER", "Visit ID": "V", "Trap ID": w["Trap ID"], "Window Closed": w["Window ID"], "Check Time": app.dtstr(EFFECTIVE)})
        data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([row])], ignore_index=True)
        app.save_data(data)
        state = workbook_state()
        res = {"check_recorded": attempt(app.undo_trial_action, app.load_data(), "set_up", result["trial_id"], result["change_ids"])}
        res["unchanged"] = all(state[n].equals(app.load_data()[n]) for n in state)
        # a clean undo works once, then the trial is gone, so a second attempt is refused
        data = app.load_data(); data["Checks"] = data["Checks"][data["Checks"]["Check ID"] != "C-LATER"]; app.save_data(data)
        data = app.load_data()
        first = attempt(app.undo_trial_action, data, "set_up", result["trial_id"], result["change_ids"])
        res["first"] = first
        res["second"] = attempt(app.undo_trial_action, app.load_data(), "set_up", result["trial_id"], result["change_ids"])
        print(json.dumps(res))
        """
    )
    assert out["check_recorded"] == "Undo isn't possible any more: a check has been recorded since this trial started."
    assert out["unchanged"] and out["first"] == "ok"
    assert out["second"].startswith("Undo isn't possible any more:")
