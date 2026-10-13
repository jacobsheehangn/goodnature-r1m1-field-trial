"""Seed data for the necropsy species-confirmation work (Phase 4). Run in a subprocess."""

# One open necropsy review on a kill the field guessed was a Mouse (camera review done: Humane), the camera
# review task already complete, and six more closed kill windows with a known confirmed / unconfirmed split
# for the Trial Performance coverage figure.
NECROPSY_SEED = """
    import datetime as dt, app, pandas as pd
    D = dt.datetime
    data = app.create_sample_data()
    for sheet in ("Sites", "Windows"):
        data[sheet] = data[sheet].replace(r"(?i)synthetic|sample", "", regex=True)
    trap = data["Traps"][(data["Traps"]["Site ID"] == "MAN") & (data["Traps"]["Product"] == "R1")].iloc[0]
    trap_id = trap["Trap ID"]
    base = {c: "" for c in app.SHEETS["Windows"]}
    def window(wid, species, rat_type, fhk, confirmed, weight, *, necropsy_task=False, video="Humane", n=0):
        row = dict(base)
        row.update({"Window ID": wid, "Trap ID": trap_id, "Product": "R1", "Build Version": "R1 Build 4.3", "Site ID": "MAN", "Camera Assigned": "Yes",
                    "Start Time": app.dtstr(D(2026, 9, 1 + n, 8)), "End Time": app.dtstr(D(2026, 9, 2 + n, 8)), "Status": "Closed", "Finding At Close": "Dead animal found",
                    "Species": species, "Rat Type": rat_type, "Field-Recorded Species": species, "Field-Recorded Rat Type": rat_type, "Species Confirmed": confirmed,
                    "Evidence Usable": "Yes", "Target Present": "Yes", "Kill Confirmed": "Yes", "Video Assessment": video, "Final Humane Kill": fhk, "Animal Weight Range": weight,
                    "Necropsy Status": "Not started" if necropsy_task else "Complete", "Necropsy Assessment": "Pending" if necropsy_task else "Supports humane kill",
                    "Valid": "Yes", "Bag ID": "MAN-0" + str(10 + n), "Review Status": "Open" if necropsy_task else "Complete", "Interaction To Kill Min": "30"})
        return row
    rows = [window("W-NEC", "Mouse", "", "Pending", "", "", necropsy_task=True, n=0)]
    # Legacy window: saved before the Field-Recorded columns existed.
    rows[0]["Field-Recorded Species"] = ""
    split = [("Rat", "Norway rat", "Yes", "Yes", "201–250 g"), ("Rat", "Ship rat", "Yes", "Yes", "151–200 g"), ("Rat", "Ship rat", "No", "Yes", "151–200 g"),
             ("Mouse", "", "Yes", "Yes", "11–20 g"), ("Rat", "Ship rat", "Yes", "", "151–200 g"), ("Rat", "Norway rat", "Yes", "", "201–250 g")]
    for i, (sp, rt, fhk, conf, wr) in enumerate(split, start=1):
        rows.append(window(f"W-K{i}", sp, rt, fhk, conf, wr, n=i))
    data["Windows"] = pd.concat([data["Windows"][~data["Windows"]["Trap ID"].eq(trap_id)], pd.DataFrame(rows)], ignore_index=True)
    app.add_followup(data, "Necropsy review", "MAN", trap_id, "V0", "W-NEC", "MAN-010", "Dead animal collected", "d", "Normal")
    app.add_followup(data, "Camera review", "MAN", trap_id, "V0", "W-NEC", "MAN-010", "Dead animal found", "d", "Normal")
    data["Followups"].loc[data["Followups"]["Follow-up Type"] == "Camera review", "Status"] = "Complete"
    app.save_data(data)
"""
