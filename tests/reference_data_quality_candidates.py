"""The Data quality candidate finder exactly as it was before Phase S
(FIELD_SPEED / TRIAL_LIFECYCLE_BRIEF.md, Phase S), kept only so the rewrite can
be compared against it. It re-filters the whole Checks table for every row, so
it is slow; do not call it from the app. Its helpers are passed in so this
file needs nothing from app.py."""
import pandas as pd


def reference_find_data_quality_candidates(data, window_minutes, parse_dt, data_quality_reviewed_check_ids):
    checks = data["Checks"].copy()
    if checks.empty:
        return []
    reviewed = data_quality_reviewed_check_ids(data)
    trap_site = data["Traps"].set_index("Trap ID")["Site ID"].to_dict()
    checks["_dt"] = checks["Check Time"].apply(parse_dt)
    checks["_site"] = checks["Trap ID"].map(trap_site)

    candidates = []
    window = pd.Timedelta(minutes=window_minutes)
    for _, row in checks.iterrows():
        check_id = str(row["Check ID"])
        if str(row.get("Excluded", "")) == "Yes" or check_id in reviewed:
            continue
        this_dt, this_site = row["_dt"], row["_site"]
        if this_dt is None or not this_site:
            continue
        site_checks = checks[(checks["_site"] == this_site) & (checks["Check ID"].astype(str) != check_id) & checks["_dt"].notna()]
        if site_checks.empty:
            gap = pd.Timedelta.max
        else:
            gap = (site_checks["_dt"] - this_dt).abs().min()
        if gap <= window:
            continue  # real activity nearby - not a candidate

        before = site_checks[site_checks["_dt"] < this_dt].sort_values("_dt")
        after = site_checks[site_checks["_dt"] > this_dt].sort_values("_dt")
        candidates.append({
            "Check ID": check_id,
            "Trap ID": row["Trap ID"],
            "Site ID": this_site,
            "Check Time": this_dt,
            "Finding": row["Finding"],
            "Window Closed": row.get("Window Closed", ""),
            "Visit ID": row.get("Visit ID", ""),
            "closest_before": before.iloc[-1]["_dt"] if not before.empty else None,
            "closest_after": after.iloc[0]["_dt"] if not after.empty else None,
        })
    candidates.sort(key=lambda c: c["Check Time"], reverse=True)
    return candidates
