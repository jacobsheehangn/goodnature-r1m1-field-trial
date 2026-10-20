"""Seed data for the Part B batch 1 task forms (Camera review, Camera issue, Trap not ready): a trial at MAN with five R1 traps, and one of each task waiting.
Run in a subprocess (app.py routes pages at import time). Times are relative to the real clock, so a "Back in service from" a day after the check is always in the
past. Trap by trap (R1 traps in route order):
  [0] a kill, bag MAN-001, camera: Camera review (with a Bag ID, so the kill form) on window W-KILL-1, evidence period 6 to 2 days ago
  [3] a trap that fired, camera: Camera review (no bag, so the full form) on window W-FIRE-1
  [1] Camera issue, no open window: the check 2 days ago found the camera "Battery low", still covering the trap
  [2] Trap not ready, no open window: the check 2 days ago found "Spring weak, wouldn't reset"
  [4] ordinary, with an open window."""

B1_SEED = """
    import datetime as dt, app, pandas as pd
    D = dt.datetime
    NOW = D.now().replace(second=0, microsecond=0)
    def ago(days, hour, minute):
        return (NOW - dt.timedelta(days=days)).replace(hour=hour, minute=minute)
    data = app.create_sample_data()
    L43 = "R1 · R1 Build 4.3"
    for sheet in ("Sites", "Windows"):
        data[sheet] = data[sheet].replace(r"(?i)synthetic|sample", "", regex=True)
    T0 = NOW - dt.timedelta(days=12)
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
    for t in (r1[0], r1[1], r1[3]):
        data["Traps"].loc[data["Traps"]["Trap ID"] == t, "Camera ID"] = "CAM-" + t[-3:]
    app.create_trial(data, "MAN", [L43], T0)
    for t in r1: app.activate_trap(data, t, T0, "start", commit=False)
    trial = app.open_trial(data, "MAN")["Trial ID"]
    def closed_window(wid, trap, start, end, finding, bag=""):
        w = {c: "" for c in app.SHEETS["Windows"]}
        w.update({"Window ID": wid, "Trap ID": trap, "Product": "R1", "Build Version": "R1 Build 4.3", "Site ID": "MAN", "Camera Assigned": "Yes",
                  "Start Time": app.dtstr(start), "End Time": app.dtstr(end), "Status": "Closed", "Finding At Close": finding, "Bag ID": bag,
                  "Final Humane Kill": "Pending" if bag else "", "Valid": "Pending", "Review Status": "Open", "Trial ID": trial})
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([w])], ignore_index=True)
    closed_window("W-KILL-1", r1[0], ago(6, 9, 15), ago(2, 8, 40), "Dead animal found", "MAN-001")
    closed_window("W-FIRE-1", r1[3], ago(6, 9, 2), ago(2, 8, 21), "Trap fired, no animal")
    app.add_followup(data, "Camera review", "MAN", r1[0], "V0", "W-KILL-1", "MAN-001", "Dead animal found", "d", "Normal")
    app.add_followup(data, "Camera review", "MAN", r1[3], "V0", "W-FIRE-1", "", "Trap fired, no animal", "d", "High")
    def close_open_window(trap, end):
        idx = data["Windows"].index[(data["Windows"]["Trap ID"] == trap) & (data["Windows"]["Status"] == "Open")][0]
        wid = data["Windows"].at[idx, "Window ID"]
        for k, v in {"End Time": app.dtstr(end), "Status": "Closed", "Finding At Close": "Trap still set, no animal", "Review Status": "Open"}.items():
            data["Windows"].at[idx, k] = v
        return wid
    def check_row(trap, when, **fields):
        row = {c: "" for c in app.SHEETS["Checks"]}
        row.update({"Check ID": "C-OLD-" + trap, "Visit ID": "VIS-OLD", "Trap ID": trap, "Check Time": app.dtstr(when), "Finding": "Trap still set, no animal"})
        row.update(fields)
        data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([row])], ignore_index=True)
    w1 = close_open_window(r1[1], ago(2, 8, 40))
    check_row(r1[1], ago(2, 8, 40), **{"Camera Condition": "Battery low", "Camera Covers Trap": "Yes", "Trap Ready After Check": "Ready"})
    app.add_followup(data, "Camera issue", "MAN", r1[1], "VIS-OLD", w1, "", "Camera issue", "d", "High")
    w2 = close_open_window(r1[2], ago(2, 8, 12))
    check_row(r1[2], ago(2, 8, 12), **{"Trap Ready After Check": "Not ready", "Notes": "Spring weak, wouldn't reset"})
    app.add_followup(data, "Trap not ready", "MAN", r1[2], "VIS-OLD", w2, "", "Spring weak, wouldn't reset", "d", "High")
    app.save_data(data)
"""

# For tests that need the trap to have something else going on before the form opens. Each runs after B1_SEED.
OTHER_TASK_OPEN = """
    import app
    d = app.load_data()
    t = d["Followups"][d["Followups"]["Follow-up Type"] == "Trap not ready"].iloc[0]
    app.add_followup(d, "Camera issue", "MAN", t["Trap ID"], t["Visit ID"], t["Window ID"], "", "Camera issue", "d", "High")
    app.save_data(d)
"""
ALREADY_RESTARTED = """
    import datetime as dt, app
    d = app.load_data()
    t = d["Followups"][d["Followups"]["Follow-up Type"] == "Camera issue"].iloc[0]
    app.start_window(d, t["Trap ID"], app.now() - dt.timedelta(hours=1))
    app.save_data(d)
"""
