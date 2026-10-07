"""Seed data for the trial-journey screens: three sites in the three states the Trap sites
card has to tell apart. Run in a subprocess (app.py routes pages at import time)."""

# MAN: a finished trial A whose five traps were deactivated; two old-build traps, two brand-new
#      traps and (at KAI) two traps ready to relocate in: the Set up pool in all three groups.
# KAI: running with no trial (untracked): the "Track as a trial" state, with a build history.
# WAI: no active traps and no trial: the "Start trial" state.
JOURNEY_SEED = """
    import datetime as dt, app, pandas as pd
    D = dt.datetime
    data = app.create_sample_data()
    for sheet in ("Sites", "Windows"):
        data[sheet] = data[sheet].replace(r"(?i)synthetic|sample", "", regex=True)
    data["Builds"] = pd.concat([data["Builds"], pd.DataFrame([["R1", "R1 Build 4.1", "Superseded", "2026-05-01", ""]], columns=data["Builds"].columns)], ignore_index=True)
    def traps_at(site, status=None, product=None):
        t = data["Traps"][data["Traps"]["Site ID"] == site]
        if status: t = t[t["Status"] == status]
        if product: t = t[t["Product"] == product]
        return t["Trap ID"].tolist()
    T0 = D(2026, 9, 1, 8, 0)
    man = traps_at("MAN", product="R1"); kai = traps_at("KAI", product="R1"); wai = traps_at("WAI")
    data["Windows"] = data["Windows"][~data["Windows"]["Trap ID"].isin(traps_at("MAN") + traps_at("WAI"))].copy()
    for t in traps_at("MAN") + wai:
        if app.trap_row(data, t)["Status"] == "Active":
            app.deactivate_trap(data, t, T0, "stage", commit=False)
    app.create_trial(data, "MAN", ["R1 · R1 Build 4.3"], T0)
    for t in man: app.activate_trap(data, t, T0, "start A", commit=False)
    for t in man: app.deactivate_trap(data, t, T0 + dt.timedelta(days=5), "end A", commit=False)
    data["Trials"].loc[data["Trials"]["Status"] == "Open", ["Status", "End Time"]] = ["Ended", app.dtstr(T0 + dt.timedelta(days=5))]
    for t in man[3:]:
        app.change_trap_build(data, t, "R1", "R1 Build 4.1", T0 + dt.timedelta(days=6), "old build", commit=False)
    for new_id in ("R1-MAN-NEW1", "R1-MAN-NEW2"):
        row = {c: "" for c in app.SHEETS["Traps"]}
        row.update({"Trap ID": new_id, "Product": "R1", "Build Version": "R1 Build 4.3", "Site ID": "MAN", "Route Order": "50", "Location": "Spot " + new_id, "Status": "Inactive"})
        data["Traps"] = pd.concat([data["Traps"], pd.DataFrame([row])], ignore_index=True)
    for t in traps_at("KAI", "Active", "M1"):
        app.deactivate_trap(data, t, T0, "single-product site", commit=False)
    app.save_data(data)
"""


# MAN is running a trial (5 R1 traps, two with cameras), a visit is in progress with 3 of 5 traps checked,
# and there is evidence waiting: a camera review and a necropsy review on a kill, plus two hardware tasks.
END_SEED = """
    import datetime as dt, app, pandas as pd
    D = dt.datetime
    data = app.create_sample_data()
    L43 = "R1 · R1 Build 4.3"
    for sheet in ("Sites", "Windows"):
        data[sheet] = data[sheet].replace(r"(?i)synthetic|sample", "", regex=True)
    T0 = D(2026, 9, 1, 8, 0)
    def traps_at(site, status=None, product=None):
        t = data["Traps"][data["Traps"]["Site ID"] == site]
        if status: t = t[t["Status"] == status]
        if product: t = t[t["Product"] == product]
        return t["Trap ID"].tolist()
    r1 = traps_at("MAN", product="R1")
    data["Windows"] = data["Windows"][~data["Windows"]["Trap ID"].isin(traps_at("MAN"))].copy()
    for t in traps_at("MAN"):
        if app.trap_row(data, t)["Status"] == "Active":
            app.deactivate_trap(data, t, T0, "stage", commit=False)
    for t in (r1[0], r1[3]):
        data["Traps"].loc[data["Traps"]["Trap ID"] == t, "Camera ID"] = "CAM-" + t[-3:]
    app.create_trial(data, "MAN", [L43], T0)
    for t in r1: app.activate_trap(data, t, T0, "start", commit=False)
    trial = app.open_trial(data, "MAN")["Trial ID"]
    kill = {c: "" for c in app.SHEETS["Windows"]}
    kill.update({"Window ID": "W-KILL-1", "Trap ID": r1[0], "Product": "R1", "Build Version": "R1 Build 4.3", "Site ID": "MAN", "Camera Assigned": "Yes",
                 "Start Time": app.dtstr(T0), "End Time": app.dtstr(T0 + dt.timedelta(days=2)), "Status": "Closed", "Finding At Close": "Dead animal found",
                 "Species": "Rat", "Bag ID": "MAN-001", "Final Humane Kill": "Pending", "Valid": "Pending", "Review Status": "Open", "Trial ID": trial})
    data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([kill])], ignore_index=True)
    app.add_followup(data, "Camera review", "MAN", r1[0], "V0", "W-KILL-1", "MAN-001", "Dead animal found", "d", "Normal")
    app.add_followup(data, "Necropsy review", "MAN", r1[0], "V0", "W-KILL-1", "MAN-001", "Dead animal collected", "d", "Normal")
    app.add_followup(data, "Trap not ready", "MAN", r1[2], "V0", "W", "", "Lure gone", "d", "High")
    app.add_followup(data, "Camera issue", "MAN", r1[1], "V0", "W", "", "Camera issue", "d", "High")
    data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([["VIS-WALK-1", "MAN", "Op", app.dtstr(D(2026, 10, 5, 8)), "", "In progress", ""]], columns=app.SHEETS["Visits"])], ignore_index=True)
    for t in r1[:3]:
        row = {c: "" for c in app.SHEETS["Checks"]}
        row.update({"Check ID": "C-" + t, "Visit ID": "VIS-WALK-1", "Trap ID": t, "Check Time": app.dtstr(D(2026, 10, 5, 9)), "Finding": "Trap still set, no animal"})
        data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([row])], ignore_index=True)
    app.save_data(data)
"""
