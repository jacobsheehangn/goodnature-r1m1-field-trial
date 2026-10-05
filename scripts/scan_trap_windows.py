"""Read-only scan for trap/window states that break the "one open window per
Active trap, none for an Inactive one" rule (TRIAL_LIFECYCLE_BRIEF.md, Phase 0).

    python scripts/scan_trap_windows.py path/to/field_trial_data_v8_6_5.xlsx

It only reads the workbook; it never writes anything, and repairs nothing.
Each repair is a data decision (what End Time to give a stray window) that
needs a person's confirmation, per record, with an audit entry.

Findings:
  A. Inactive traps that have an open window.
  B. Active traps with MORE than one open window.
  C. Active traps with NO open window, classified rather than lumped:
       - awaiting service: an open "Trap not ready" / "Camera issue" follow-up
         exists. After a check where the trap isn't service-ready or the camera
         isn't ready, the check-save flow deliberately does not open a new
         window, so this is a legitimate state, not damage.
       - trap missing: the trap's latest window closed with the finding "Trap
         missing". The same flow deliberately starts no window until the trap is
         redeployed, so this is also a legitimate state. (The brief names only
         the follow-up case; this one follows from the same code.)
       - DEFECT: neither of the above.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HARDWARE_FOLLOWUPS = ("Trap not ready", "Camera issue")


def _sheet(path: Path, name: str) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=name, dtype=str).fillna("")


def scan(path: Path) -> dict:
    traps = _sheet(path, "Traps")
    windows = _sheet(path, "Windows")
    followups = _sheet(path, "Followups")

    open_windows = windows[windows["Status"] == "Open"]
    open_by_trap = open_windows.groupby("Trap ID")
    open_counts = open_by_trap.size().to_dict()

    inactive_with_open = []
    for _, trap in traps[traps["Status"] == "Inactive"].iterrows():
        n = open_counts.get(trap["Trap ID"], 0)
        if n:
            rows = open_windows[open_windows["Trap ID"] == trap["Trap ID"]]
            inactive_with_open.append({
                "Trap ID": trap["Trap ID"], "Site ID": trap["Site ID"], "Build": trap["Build Version"],
                "Open windows": n, "Window IDs": ", ".join(rows["Window ID"]),
                "Started": ", ".join(rows["Start Time"]),
            })

    active = traps[traps["Status"] == "Active"]
    multiple_open = [
        {"Trap ID": t["Trap ID"], "Site ID": t["Site ID"], "Open windows": open_counts[t["Trap ID"]],
         "Window IDs": ", ".join(open_windows[open_windows["Trap ID"] == t["Trap ID"]]["Window ID"])}
        for _, t in active.iterrows() if open_counts.get(t["Trap ID"], 0) > 1
    ]

    open_hardware = followups[(followups["Status"] == "Open") & (followups["Follow-up Type"].isin(HARDWARE_FOLLOWUPS))]
    hardware_by_trap = open_hardware.groupby("Trap ID")["Follow-up Type"].apply(lambda s: ", ".join(sorted(set(s)))).to_dict()

    awaiting_service, trap_missing, defects = [], [], []
    for _, trap in active.iterrows():
        trap_id = trap["Trap ID"]
        if open_counts.get(trap_id, 0):
            continue
        history = windows[windows["Trap ID"] == trap_id].copy()
        history["_end"] = pd.to_datetime(history["End Time"], errors="coerce")
        last = history.sort_values("_end").iloc[-1] if not history.empty else None
        info = {
            "Trap ID": trap_id, "Site ID": trap["Site ID"], "Build": trap["Build Version"],
            "Windows on record": len(history),
            "Last window ended": last["End Time"] if last is not None else "(none)",
            "Last finding": last["Finding At Close"] if last is not None else "(none)",
        }
        if trap_id in hardware_by_trap:
            awaiting_service.append({**info, "Open follow-up": hardware_by_trap[trap_id]})
        elif last is not None and last["Finding At Close"] == "Trap missing":
            trap_missing.append(info)
        else:
            defects.append(info)

    return {
        "counts": {
            "Traps": len(traps), "Active": len(active), "Inactive": int((traps["Status"] == "Inactive").sum()),
            "Windows": len(windows), "Open windows": len(open_windows),
        },
        "A_inactive_with_open_window": inactive_with_open,
        "B_active_with_multiple_open_windows": multiple_open,
        "C_active_without_open_window": {
            "awaiting_service (legitimate)": awaiting_service,
            "trap_missing (legitimate)": trap_missing,
            "DEFECT (needs a decision)": defects,
        },
    }


def _table(rows: list) -> str:
    if not rows:
        return "    none\n"
    frame = pd.DataFrame(rows)
    return "\n".join("    " + line for line in frame.to_string(index=False).splitlines()) + "\n"


def format_report(result: dict) -> str:
    c = result["counts"]
    out = [
        "STRAY WINDOW SCAN (read-only)",
        f"Traps {c['Traps']} (Active {c['Active']}, Inactive {c['Inactive']}) | Windows {c['Windows']} | Open windows {c['Open windows']}",
        "",
        f"A. Inactive traps with an open window: {len(result['A_inactive_with_open_window'])}",
        _table(result["A_inactive_with_open_window"]),
        f"B. Active traps with more than one open window: {len(result['B_active_with_multiple_open_windows'])}",
        _table(result["B_active_with_multiple_open_windows"]),
        "C. Active traps with no open window:",
    ]
    for label, rows in result["C_active_without_open_window"].items():
        out.append(f"  {label}: {len(rows)}")
        out.append(_table(rows))
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/scan_trap_windows.py path/to/workbook.xlsx")
    print(format_report(scan(Path(sys.argv[1]))))
