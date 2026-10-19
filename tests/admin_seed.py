"""Seed data for the administration screens (Part B batch 2a): the trial-journey END_SEED (Mangaroa Farm running a trial with five R1 traps, Kaitoke Shed with
no trial and Active traps) with the visit that was in progress completed (so a trap can move), one Inactive trap that has history (R1-MAN-005: its window is
closed, so it cannot be deleted) and one that has none (R1-MAN-NEW1: staged, never activated, so it can be). Run in a subprocess."""
from journey_seed import END_SEED

ADMIN_EXTRA = """
    import datetime as dt, app, pandas as pd
    d = app.load_data()
    d["Visits"].loc[d["Visits"]["Status"] == "In progress", ["Status", "End Time"]] = ["Completed", app.dtstr(app.now())]
    d["Traps"].loc[d["Traps"]["Trap ID"].isin(["R1-MAN-001"]), "Notes"] = "Moved 2 m uphill after the flood."
    app.deactivate_trap(d, "R1-MAN-005", app.now() - dt.timedelta(hours=1), "Trap damaged by stock.", commit=False)
    row = {c: "" for c in app.SHEETS["Traps"]}
    row.update({"Trap ID": "R1-MAN-NEW1", "Product": "R1", "Build Version": "R1 Build 4.3", "Site ID": "MAN", "Route Order": "50", "Location": "Spot new", "Status": "Inactive"})
    d["Traps"] = pd.concat([d["Traps"], pd.DataFrame([row])], ignore_index=True)
    app.save_data(d)
"""
ADMIN_SEED = END_SEED + "\n" + ADMIN_EXTRA
