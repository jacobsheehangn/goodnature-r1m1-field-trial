from __future__ import annotations

import uuid
import hashlib
import hmac
import os
import shutil
import re
from io import BytesIO
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import html
from PIL import Image, ImageOps

APP_TITLE = "R1/M1 Field Trial — v8.6.67 Message Contrast and Header Clearance Fix"
APP_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("R1M1_DATA_DIR", str(APP_DIR))).expanduser().resolve()
DATA_FILE = DATA_ROOT / "field_trial_data_v8_6_5.xlsx"
DEMO_SEED_DATA_FILE = APP_DIR / "field_trial_data_v8_6_5.xlsx"
CLEAN_SEED_DATA_FILE = APP_DIR / "field_trial_data_clean_seed.xlsx"
SEED_MODE = os.environ.get("R1M1_SEED_MODE", "demo").strip().lower()
SEED_DATA_FILE = CLEAN_SEED_DATA_FILE if SEED_MODE == "clean" else DEMO_SEED_DATA_FILE
DEPLOYMENT_ENVIRONMENT = os.environ.get("R1M1_ENVIRONMENT", "local").strip().lower()
APP_PASSWORD = os.environ.get("R1M1_APP_PASSWORD", "")
ALLOW_NO_AUTH = os.environ.get("R1M1_ALLOW_NO_AUTH", "false").strip().lower() == "true"
EVIDENCE_DIR = DATA_ROOT / "evidence"
BACKUP_DIR = DATA_ROOT / "backups"
MAX_RAW_PHOTO_BYTES = 20 * 1024 * 1024
MAX_SAVED_PHOTO_BYTES = 2 * 1024 * 1024
MAX_PHOTO_DIMENSION = 1600

SHEETS = {
    "Sites": ["Site ID", "Site Name", "Visit Interval Days", "Mobile Coverage Confirmed", "Status", "Notes"],
    "Builds": ["Product", "Build Version", "Build Status", "First Active Date", "Notes"],
    "Traps": ["Trap ID", "Product", "Build Version", "Site ID", "Route Order", "Location", "Camera ID", "Deployment Start", "Setup Image Link", "Status", "Notes"],
    "Visits": ["Visit ID", "Site ID", "Operator", "Start Time", "End Time", "Status", "Notes"],
    "Checks": ["Check ID", "Visit ID", "Trap ID", "Window Closed", "Check Time", "Finding", "Species", "Rat Type", "Animal Condition When Found", "Bag ID", "Animal Cleared", "Animal Bagged", "Lure Condition", "Relured", "Reset Required", "Trap Reset", "Trap Ready After Check", "Trap Function", "Site Condition", "Camera Condition", "Camera Covers Trap", "Camera Adjusted", "New Window", "Notes"],
    "Windows": ["Window ID", "Trap ID", "Product", "Build Version", "Site ID", "Camera Assigned", "Start Time", "End Time", "Status", "End Reason", "Finding At Close", "Species", "Rat Type", "Evidence Usable", "Target Present", "Interaction Level", "Entered Strike Area", "Trap Activated", "Activation Evidence", "Kill Confirmed", "Outcome", "First Target Time", "First Interaction Time", "Trigger Time", "Kill Time", "Time To First Target Hr", "Time To First Interaction Hr", "Interaction To Trigger Min", "Interaction To Kill Min", "Time To Kill Hr", "Video Assessment", "Video Link", "Necropsy Status", "Necropsy Assessment", "Animal Weight Range", "Necropsy Data Link", "Necropsy Measurements", "Final Humane Kill", "Valid", "Bag ID", "Review Status", "Notes"],
    "Followups": ["Follow-up ID", "Follow-up Type", "Site ID", "Trap ID", "Visit ID", "Window ID", "Bag ID", "Created Time", "Priority", "Reason", "Data Required", "Status", "Completed Time", "Notes"],
    "Audit Log": ["Change ID", "Changed Time", "Record Type", "Record ID", "Field", "Previous Value", "New Value", "Reason"],
    "Photos": ["Photo ID", "Check ID", "Window ID", "Trap ID", "Site ID", "Bag ID", "Capture Time", "Photo Type", "File Path", "Notes"],
}

FINDINGS = ["Trap still set, no animal", "Dead animal found", "Trap fired, no animal", "Trap disturbed", "Trap missing", "Unable to check"]
LURE = ["Fresh", "Present/good", "Partly eaten", "Gone", "Dry", "Mouldy", "Contaminated", "Unknown"]
CAMERA = ["Working", "Offline", "Battery low", "Poor view", "Blocked view", "Missing", "Unsure"]
SPECIES = ["Rat", "Mouse", "Non-target", "Unknown"]
ANIMAL_CONDITION = ["Dead and apparently normal", "Dead with obvious injury concern", "Alive and trapped", "Alive and maimed", "Unable to assess"]
ANIMAL_WEIGHT_RANGES = ["0–50 g", "51–100 g", "101–150 g", "151–200 g", "201–250 g", "251–300 g", "301–350 g", "351–400 g", "400+ g"]
RAT_TYPES = ["Norway rat", "Ship rat", "Unclear"]


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def dtstr(value: Optional[datetime] = None) -> str:
    return (value or now()).strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(value) -> Optional[datetime]:
    if value is None or value == "" or pd.isna(value):
        return None
    try:
        return pd.to_datetime(value).to_pydatetime()
    except Exception:
        return None


def make_id(prefix: str) -> str:
    return f"{prefix}-{now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


SITE_CODE_LINKED_SHEETS = ["Traps", "Visits", "Windows", "Followups", "Photos"]


def normalise_site_code(value: str) -> str:
    return str(value or "").strip().upper()


def validate_site_code(value: str) -> Optional[str]:
    code = normalise_site_code(value)
    if not code:
        return "Site code is required."
    if not re.fullmatch(r"[A-Z0-9]{2,8}", code):
        return "Use 2–8 letters or numbers with no spaces or punctuation."
    return None


def site_code_link_counts(data: Dict[str, pd.DataFrame], site_id: str) -> Dict[str, int]:
    """Count records affected by a site-code rename."""
    site_code = normalise_site_code(site_id)
    counts = {}
    for sheet_name in ["Sites"] + SITE_CODE_LINKED_SHEETS:
        frame = data.get(sheet_name)
        if frame is None or "Site ID" not in frame.columns:
            counts[sheet_name] = 0
            continue
        counts[sheet_name] = int(
            (frame["Site ID"].astype(str).str.upper() == site_code).sum()
        )
    return counts


def _safe_relative_photo_path(value: str) -> Optional[Path]:
    """Return a normalised relative evidence path, or None when unsafe/blank."""
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Unsafe stored photo path: {raw}")
    return candidate


def plan_site_photo_migration(
    data: Dict[str, pd.DataFrame], old_id: str, new_id: str
):
    """Return updated photo metadata and a collision-checked file move plan."""
    old_code = normalise_site_code(old_id)
    new_code = normalise_site_code(new_id)
    updated = data["Photos"].copy(deep=True)
    moves = []
    planned_destinations = set()

    if updated.empty:
        return updated, moves

    mask = updated["Site ID"].astype(str).str.upper() == old_code
    for idx in updated.index[mask]:
        rel_path = _safe_relative_photo_path(updated.at[idx, "File Path"])
        updated.at[idx, "Site ID"] = new_code
        if rel_path is None:
            continue

        parts = list(rel_path.parts)
        if len(parts) < 2 or parts[0].lower() != "evidence" or parts[1].upper() != old_code:
            # Preserve custom/historic paths while correcting their Site ID metadata.
            continue

        parts[1] = new_code
        new_rel = Path(*parts)
        source = DATA_ROOT / rel_path
        destination = DATA_ROOT / new_rel

        if not source.exists():
            # Do not rewrite a missing file to a new location that also does not exist.
            if destination.exists():
                updated.at[idx, "File Path"] = new_rel.as_posix()
            continue

        destination_key = str(destination.resolve())
        if destination_key in planned_destinations or destination.exists():
            raise ValueError(
                f"Cannot rename site because a photo already exists at {new_rel.as_posix()}."
            )
        planned_destinations.add(destination_key)
        moves.append((source, destination))
        updated.at[idx, "File Path"] = new_rel.as_posix()

    return updated, moves


def apply_file_moves(moves):
    """Move evidence files and return the completed move list for rollback."""
    completed = []
    try:
        for source, destination in moves:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            completed.append((source, destination))
        return completed
    except Exception:
        rollback_file_moves(completed)
        raise


def rollback_file_moves(completed_moves) -> None:
    """Restore moved files to their original paths."""
    for source, destination in reversed(completed_moves):
        try:
            if destination.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
        except Exception:
            pass


def remove_empty_evidence_directories(site_code: str) -> None:
    """Remove empty directories left behind after a successful site rename."""
    root = EVIDENCE_DIR / normalise_site_code(site_code)
    if not root.exists():
        return
    directories = [p for p in root.rglob("*") if p.is_dir()]
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass


def rename_site_code(data: Dict[str, pd.DataFrame], old_id: str, new_id: str, reason: str):
    """Return updated workbook data and a checked evidence-file migration plan."""
    old_code = normalise_site_code(old_id)
    new_code = normalise_site_code(new_id)
    error = validate_site_code(new_code)
    if error:
        raise ValueError(error)
    if old_code == new_code:
        raise ValueError("Enter a different site code.")
    if old_code not in data["Sites"]["Site ID"].astype(str).str.upper().tolist():
        raise ValueError("The original site code could not be found.")
    existing_codes = data["Sites"]["Site ID"].astype(str).str.upper().tolist()
    if new_code in existing_codes:
        raise ValueError("That site code already exists.")

    updated = {name: frame.copy(deep=True) for name, frame in data.items()}
    counts = site_code_link_counts(updated, old_code)

    site_mask = updated["Sites"]["Site ID"].astype(str).str.upper() == old_code
    updated["Sites"].loc[site_mask, "Site ID"] = new_code

    for sheet_name in ["Traps", "Visits", "Windows", "Followups"]:
        frame = updated.get(sheet_name)
        if frame is None or "Site ID" not in frame.columns:
            continue
        mask = frame["Site ID"].astype(str).str.upper() == old_code
        updated[sheet_name].loc[mask, "Site ID"] = new_code

    migrated_photos, file_moves = plan_site_photo_migration(updated, old_code, new_code)
    updated["Photos"] = migrated_photos

    detail = ", ".join(f"{name}: {count}" for name, count in counts.items() if count)
    audit_row = {
        "Change ID": make_id("CHANGE"),
        "Changed Time": dtstr(),
        "Record Type": "Site",
        "Record ID": old_code,
        "Field": "Site ID",
        "Previous Value": old_code,
        "New Value": new_code,
        "Reason": f"{reason.strip()} | Linked records updated: {detail}",
    }
    updated["Audit Log"] = pd.concat(
        [updated["Audit Log"], pd.DataFrame([audit_row], columns=SHEETS["Audit Log"])],
        ignore_index=True,
    )
    return updated, counts, file_moves


def commit_site_code_rename(
    data: Dict[str, pd.DataFrame], old_id: str, new_id: str, reason: str
):
    """Move evidence, save workbook atomically, and roll back files if save fails."""
    updated, counts, move_plan = rename_site_code(data, old_id, new_id, reason)
    completed_moves = apply_file_moves(move_plan)
    try:
        save_data(updated)
    except Exception:
        rollback_file_moves(completed_moves)
        raise
    remove_empty_evidence_directories(old_id)
    return updated, counts, len(completed_moves)


def next_bag_id(data, site_id: str) -> str:
    prefix = (site_id or "BAG").upper()[:3]
    existing = pd.concat([data["Checks"].get("Bag ID", pd.Series(dtype=str)), data["Windows"].get("Bag ID", pd.Series(dtype=str))], ignore_index=True).astype(str)
    used = set(existing[existing.str.match(rf"^{prefix}-\d{{3}}$")].tolist())
    number = 1
    while f"{prefix}-{number:03d}" in used:
        number += 1
    return f"{prefix}-{number:03d}"


def refresh_review_status(data, window_id: str) -> None:
    if not window_id:
        return
    idxs = data["Windows"].index[data["Windows"]["Window ID"] == window_id].tolist()
    if not idxs:
        return
    tasks = data["Followups"][(data["Followups"]["Window ID"] == window_id) & (data["Followups"]["Follow-up Type"].isin(["Camera review", "Necropsy review"]))]
    if tasks.empty:
        status = "Not required"
    elif (tasks["Status"] == "Open").any():
        status = "Open"
    else:
        status = "Complete"
    data["Windows"].at[idxs[0], "Review Status"] = status


def blank(sheet: str) -> pd.DataFrame:
    return pd.DataFrame(columns=SHEETS[sheet])


def create_sample_data() -> Dict[str, pd.DataFrame]:
    data = {name: blank(name) for name in SHEETS}
    data["Sites"] = pd.DataFrame([
        ["MAN", "Mangaroa Farm", "3", "Yes", "Active", "Sample site"],
        ["KAI", "Kaitoke Shed", "3", "Yes", "Active", "Sample site"],
        ["WAI", "Wairarapa Block", "3", "Yes", "Active", "Sample site"],
    ], columns=SHEETS["Sites"])
    data["Builds"] = pd.DataFrame([
        ["R1", "R1 Build 4.3", "Current", "2026-07-12", "Latest sample build"],
        ["R1", "R1 Build 4.2", "Superseded", "2026-06-21", "Historical comparison"],
        ["M1", "M1 Build 3.7", "Current", "2026-07-18", "Latest sample build"],
    ], columns=SHEETS["Builds"])
    traps = []
    for site, count in [("MAN", 6), ("KAI", 4), ("WAI", 5)]:
        for i in range(1, count + 1):
            product = "M1" if i % 4 == 0 else "R1"
            build = "M1 Build 3.7" if product == "M1" else "R1 Build 4.3"
            camera_id = f"CAM-{site}-{i:03d}" if i == 1 else ""
            traps.append([f"{product}-{site}-{i:03d}", product, build, site, str(i), f"Trap {i}", camera_id, dtstr(now() - timedelta(days=14)), "", "Active", ""])
    data["Traps"] = pd.DataFrame(traps, columns=SHEETS["Traps"])
    start = now() - timedelta(hours=60)
    for _, t in data["Traps"].iterrows():
        record = {column: "" for column in SHEETS["Windows"]}
        record.update({
            "Window ID": make_id(f"{t['Trap ID']}-W"),
            "Trap ID": t["Trap ID"], "Product": t["Product"], "Build Version": t["Build Version"], "Site ID": t["Site ID"],
            "Camera Assigned": "Yes" if str(t["Camera ID"]).strip() else "No",
            "Start Time": dtstr(start), "Status": "Open", "Evidence Usable": "Pending", "Target Present": "Pending",
            "Interaction Level": "Pending", "Entered Strike Area": "Pending", "Trap Activated": "Pending", "Kill Confirmed": "Pending",
            "Outcome": "Pending", "Video Assessment": "Pending", "Necropsy Status": "Not started", "Necropsy Assessment": "Pending",
            "Final Humane Kill": "Pending", "Valid": "Pending", "Review Status": "Not required", "Notes": "Sample open window",
        })
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([record])], ignore_index=True)
        data["Windows"] = data["Windows"][SHEETS["Windows"]]
    return data



def require_authentication() -> None:
    """Require the shared pilot password before loading or displaying trial data."""
    if st.session_state.get("authenticated"):
        return

    if not APP_PASSWORD:
        if ALLOW_NO_AUTH and DEPLOYMENT_ENVIRONMENT == "local":
            st.session_state.authenticated = True
            return
        st.error("App access is not configured.")
        st.caption("Set the R1M1_APP_PASSWORD environment variable, then restart the app.")
        st.stop()

    logo_path = APP_DIR / "goodnature_logo.png"
    left, centre, right = st.columns([1, 1.3, 1])
    with centre:
        if logo_path.exists():
            st.image(str(logo_path), width=190)
        st.title("R1/M1 field trial")
        st.caption("Enter the trial password to continue.")
        with st.form("login_form", clear_on_submit=False):
            supplied_password = st.text_input(
                "Password",
                type="password",
                autocomplete="current-password",
            )
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

        if submitted:
            if hmac.compare_digest(supplied_password, APP_PASSWORD):
                st.session_state.authenticated = True
                st.session_state.failed_login_attempts = 0
                st.rerun()
            else:
                attempts = int(st.session_state.get("failed_login_attempts", 0)) + 1
                st.session_state.failed_login_attempts = attempts
                st.error("Incorrect password.")
                if attempts >= 5:
                    st.caption("Several attempts have failed. Check the password with the trial lead.")

        st.caption("Trial data is restricted to authorised Goodnature users.")
    st.stop()


def show_environment_banner() -> None:
    if DEPLOYMENT_ENVIRONMENT == "staging":
        st.markdown(
            """
            <div class="staging-banner" role="status">
              <span class="staging-banner-mobile"><strong>STAGING</strong> — Setup and testing only</span>
              <span class="staging-banner-desktop"><strong>STAGING</strong> — Setup and testing only. Do not record real field results.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif DEPLOYMENT_ENVIRONMENT not in {"production", "local"}:
        st.info(f"Environment: {DEPLOYMENT_ENVIRONMENT}")


def ensure_storage_ready() -> None:
    """Create and verify the configured durable-data directories."""
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    probe = DATA_ROOT / ".r1m1_write_test"
    try:
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        raise RuntimeError(f"Data storage is not writable: {DATA_ROOT}") from exc


def storage_is_potentially_ephemeral() -> bool:
    path = str(DATA_ROOT).lower()
    return path.startswith("/tmp") or path.startswith("/var/tmp") or "/.streamlit/" in path


def save_data(data: Dict[str, pd.DataFrame]) -> None:
    """Atomically replace the workbook and retain a timestamped recovery copy."""
    ensure_storage_ready()
    temp_file = DATA_ROOT / f".{DATA_FILE.name}.{uuid.uuid4().hex}.tmp.xlsx"
    backup_file = None
    try:
        with pd.ExcelWriter(temp_file, engine="openpyxl") as writer:
            for name, cols in SHEETS.items():
                df = data.get(name, blank(name)).copy()
                for c in cols:
                    if c not in df.columns:
                        df[c] = ""
                df[cols].to_excel(writer, sheet_name=name, index=False)
        if DATA_FILE.exists():
            backup_file = BACKUP_DIR / f"{DATA_FILE.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:6]}.xlsx"
            shutil.copy2(DATA_FILE, backup_file)
        os.replace(temp_file, DATA_FILE)
        backups = sorted(BACKUP_DIR.glob(f"{DATA_FILE.stem}_*.xlsx"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old_backup in backups[20:]:
            old_backup.unlink(missing_ok=True)
    finally:
        temp_file.unlink(missing_ok=True)


def load_data() -> Dict[str, pd.DataFrame]:
    ensure_storage_ready()
    if not DATA_FILE.exists() and SEED_DATA_FILE.exists() and SEED_DATA_FILE != DATA_FILE:
        shutil.copy2(SEED_DATA_FILE, DATA_FILE)
    if not DATA_FILE.exists():
        data = create_sample_data(); save_data(data); return data
    out = {}
    for name, cols in SHEETS.items():
        try: df = pd.read_excel(DATA_FILE, sheet_name=name, dtype=str).fillna("")
        except Exception: df = blank(name)
        for c in cols:
            if c not in df.columns: df[c] = ""
        out[name] = df[cols]
    return out


def site_name(data, site_id):
    r = data["Sites"][data["Sites"]["Site ID"] == site_id]
    return r.iloc[0]["Site Name"] if not r.empty else site_id


def trap_row(data, trap_id):
    return data["Traps"][data["Traps"]["Trap ID"] == trap_id].iloc[0]


def trap_location_label(trap) -> str:
    """Return user-facing trap location without legacy route terminology."""
    if trap is None:
        return "No location recorded"

    raw_location = str(trap.get("Location", "") or "").strip()
    raw_order = trap.get("Route Order", "")

    try:
        trap_number = int(float(raw_order))
    except (TypeError, ValueError):
        trap_number = None

    if not raw_location:
        return f"Trap {trap_number}" if trap_number is not None else "No location recorded"

    if re.fullmatch(r"Route point\s*\d+", raw_location, flags=re.IGNORECASE):
        return f"Trap {trap_number}" if trap_number is not None else re.sub(
            r"Route point", "Trap", raw_location, flags=re.IGNORECASE
        )

    return raw_location


def active_visit(data, site_id):
    r = data["Visits"][(data["Visits"]["Site ID"] == site_id) & (data["Visits"]["Status"] == "In progress")]
    return None if r.empty else r.iloc[-1]


def start_visit_now(data, site_id: str, operator: str) -> str:
    """Create a visit in the background at the current device time."""
    vid = make_id(f"VIS-{site_id}")
    row = [vid, site_id, (operator or "Unknown").strip() or "Unknown", dtstr(), "", "In progress", ""]
    data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([row], columns=SHEETS["Visits"])], ignore_index=True)
    save_data(data)
    return vid


def latest_completed_visit(data, site_id):
    r = data["Visits"][(data["Visits"]["Site ID"] == site_id) & (data["Visits"]["Status"] == "Complete")].copy()
    if r.empty: return None
    r["_end"] = pd.to_datetime(r["End Time"], errors="coerce")
    return r.sort_values("_end").iloc[-1]


def open_window(data, trap_id):
    r = data["Windows"][(data["Windows"]["Trap ID"] == trap_id) & (data["Windows"]["Status"] == "Open")]
    return None if r.empty else r.sort_values("Start Time").iloc[-1]


def start_window(data, trap_id, when):
    t = trap_row(data, trap_id)
    wid = make_id(f"{trap_id}-W")
    record = {column: "" for column in SHEETS["Windows"]}
    record.update({
        "Window ID": wid,
        "Trap ID": trap_id,
        "Product": t["Product"],
        "Build Version": t["Build Version"],
        "Site ID": t["Site ID"],
        "Camera Assigned": "Yes" if str(t["Camera ID"]).strip() else "No",
        "Start Time": dtstr(when),
        "Status": "Open",
        "Evidence Usable": "Pending",
        "Target Present": "Pending",
        "Interaction Level": "Pending",
        "Entered Strike Area": "Pending",
        "Trap Activated": "Pending",
        "Kill Confirmed": "Pending",
        "Outcome": "Pending",
        "Video Assessment": "Pending",
        "Necropsy Status": "Not started",
        "Necropsy Assessment": "Pending",
        "Final Humane Kill": "Pending",
        "Valid": "Pending",
        "Review Status": "Not required",
        "Notes": "Started after line check and relure",
    })
    data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([record])], ignore_index=True)
    data["Windows"] = data["Windows"][SHEETS["Windows"]]
    return wid


def close_window(data, trap_id, when, finding, bag_id):
    w = open_window(data, trap_id)
    if w is None: return ""
    idx = data["Windows"].index[data["Windows"]["Window ID"] == w["Window ID"]][0]
    for k, v in {"End Time": dtstr(when), "Status": "Closed", "End Reason": "Scheduled line check and relure", "Finding At Close": finding, "Bag ID": bag_id}.items():
        data["Windows"].at[idx, k] = v
    assessable = finding not in ["Trap missing", "Unable to check"]
    data["Windows"].at[idx, "Review Status"] = "Open" if assessable else "Not required"
    return str(w["Window ID"])


def add_followup(data, followup_type, site_id, trap_id, visit_id, window_id, bag_id, reason, required, priority):
    row = [make_id("FU"), followup_type, site_id, trap_id, visit_id, window_id, bag_id, dtstr(), priority, reason, required, "Open", "", ""]
    data["Followups"] = pd.concat([data["Followups"], pd.DataFrame([row], columns=SHEETS["Followups"])], ignore_index=True)


def go(page: str, **kwargs):
    """Navigate and reset the next page to its top."""
    st.session_state.page = page
    for k, v in kwargs.items():
        st.session_state[k] = v
    st.session_state.scroll_to_top_once = True
    st.rerun()


def set_page(page: str, **kwargs):
    """Update navigation state for a button callback; Streamlit reruns once automatically."""
    st.session_state.page = page
    for k, v in kwargs.items():
        st.session_state[k] = v
    st.session_state.scroll_to_top_once = True


def request_scroll_to_top():
    st.session_state.scroll_to_top_once = True


def scroll_to_top_once():
    """Reset Streamlit's current page after navigation and rerender settling."""
    if not st.session_state.pop("scroll_to_top_once", False):
        return
    components.html(
        """
        <script>
        (() => {
          const parent = window.parent;
          const doc = parent.document;

          const reset = () => {
            const targets = [
              doc.querySelector('[data-testid="stMainScrollContainer"]'),
              doc.querySelector('[data-testid="stAppViewContainer"] .main'),
              doc.querySelector('section.main'),
              doc.scrollingElement,
              doc.documentElement,
              doc.body
            ].filter(Boolean);

            targets.forEach((target) => {
              try {
                target.scrollTo({top: 0, left: 0, behavior: 'auto'});
              } catch (_) {
                target.scrollTop = 0;
                target.scrollLeft = 0;
              }
            });

            try {
              parent.scrollTo({top: 0, left: 0, behavior: 'auto'});
            } catch (_) {
              parent.scrollTo(0, 0);
            }
          };

          reset();
          requestAnimationFrame(reset);
          [80, 200, 450, 900].forEach((delay) => window.setTimeout(reset, delay));
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def photo_session_key(visit_id: str, trap_id: str) -> str:
    return f"captured_photos_{visit_id}_{trap_id}"


def photo_capture_mode_key(visit_id: str, trap_id: str) -> str:
    return f"photo_capture_mode_{visit_id}_{trap_id}"


def photo_widget_nonce_key(visit_id: str, trap_id: str) -> str:
    return f"photo_widget_nonce_{visit_id}_{trap_id}"


def add_pending_photo(
    visit_id: str,
    trap_id: str,
    raw_bytes: bytes,
    mime_type: str,
    photo_type: str,
    source: str,
) -> bool:
    """Add one unique image to the pending trap check."""
    photo_key = photo_session_key(visit_id, trap_id)
    st.session_state.setdefault(photo_key, [])
    token = hashlib.sha256(raw_bytes).hexdigest()
    existing_tokens = {photo.get("token") for photo in st.session_state[photo_key]}
    if token in existing_tokens:
        return False
    st.session_state[photo_key].append({
        "bytes": raw_bytes,
        "mime": mime_type or "image/jpeg",
        "photo_type": photo_type,
        "captured_time": dtstr(),
        "notes": "",
        "source": source,
        "token": token,
    })
    return True


def render_check_photo_capture(visit_id: str, trap_id: str) -> None:
    """Upload-only photo flow. No camera stream or device camera request."""
    photo_key = photo_session_key(visit_id, trap_id)
    mode_key = photo_capture_mode_key(visit_id, trap_id)
    nonce_key = photo_widget_nonce_key(visit_id, trap_id)
    st.session_state.setdefault(photo_key, [])
    st.session_state.setdefault(mode_key, "")
    st.session_state.setdefault(nonce_key, 0)

    photos = st.session_state[photo_key]
    photo_type = st.selectbox(
        "Photo type",
        ["Animal in trap", "Head / ears", "Strike location", "Trap condition", "Other"],
        key=f"photo_type_{trap_id}_{visit_id}",
    )

    upload_label = "Add another photo" if photos else "Add photo"
    if st.button(
        upload_label,
        key=f"open_upload_{trap_id}_{visit_id}",
        use_container_width=True,
    ):
        st.session_state[mode_key] = "upload"
        st.rerun()

    mode = st.session_state.get(mode_key, "")
    nonce = int(st.session_state.get(nonce_key, 0))

    if mode == "upload":
        with app_card():
            st.markdown("**Add photo**")
            st.caption(
                "Choose one or more images from this device. On mobile, use the phone's normal image picker."
            )
            uploaded = st.file_uploader(
                "Choose images",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                key=f"photo_upload_{trap_id}_{visit_id}_{nonce}",
            )
            if uploaded:
                added_count = 0
                duplicate_count = 0
                for uploaded_file in uploaded:
                    added = add_pending_photo(
                        visit_id,
                        trap_id,
                        uploaded_file.getvalue(),
                        uploaded_file.type or "image/jpeg",
                        photo_type,
                        "Upload",
                    )
                    if added:
                        added_count += 1
                    else:
                        duplicate_count += 1
                st.session_state[mode_key] = ""
                st.session_state[nonce_key] = nonce + 1
                message = f"{added_count} photo{'s' if added_count != 1 else ''} added."
                if duplicate_count:
                    message += f" {duplicate_count} duplicate{'s' if duplicate_count != 1 else ''} skipped."
                st.session_state[f"photo_feedback_{visit_id}_{trap_id}"] = message
                st.rerun()

            if st.button("Cancel", key=f"cancel_upload_{trap_id}_{visit_id}"):
                st.session_state[mode_key] = ""
                st.session_state[nonce_key] = nonce + 1
                st.rerun()

    feedback_key = f"photo_feedback_{visit_id}_{trap_id}"
    feedback = st.session_state.pop(feedback_key, None)
    if feedback:
        st.success(feedback)

    if photos:
        st.caption(
            f"{len(photos)} photo{'s' if len(photos) != 1 else ''} ready to save with this check"
        )
        for photo_index, photo in enumerate(list(photos)):
            with app_card():
                st.image(
                    photo["bytes"],
                    caption=f"{photo.get('photo_type', 'Photo')} · {photo.get('source', 'Image')}",
                    width=180,
                )
                if st.button(
                    "Remove photo",
                    key=f"remove_photo_{trap_id}_{visit_id}_{photo_index}",
                ):
                    st.session_state[photo_key].pop(photo_index)
                    st.rerun()



def compress_photo_bytes(raw_bytes: bytes) -> bytes:
    """Normalise phone images to a bounded JPEG suitable for field evidence."""
    if not raw_bytes:
        raise ValueError("The captured photo is empty.")
    if len(raw_bytes) > MAX_RAW_PHOTO_BYTES:
        raise ValueError("The captured photo is larger than 20 MB. Retake it at a lower resolution.")
    try:
        image = Image.open(BytesIO(raw_bytes))
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
    except Exception as exc:
        raise ValueError("The captured file is not a readable image.") from exc

    image.thumbnail((MAX_PHOTO_DIMENSION, MAX_PHOTO_DIMENSION), Image.Resampling.LANCZOS)
    qualities = [82, 74, 66, 58]
    output = b""
    for quality in qualities:
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
        output = buffer.getvalue()
        if len(output) <= MAX_SAVED_PHOTO_BYTES:
            return output
    if len(output) > MAX_SAVED_PHOTO_BYTES:
        raise ValueError("The photo could not be reduced below 2 MB. Retake it with less zoom or detail.")
    return output


def prepare_check_photos(photos, check_id: str, window_id: str, trap_id: str, site_id: str, bag_id: str):
    """Compress and save files, returning metadata rows and paths for rollback."""
    if not photos:
        return [], []
    folder = EVIDENCE_DIR / site_id / (bag_id or trap_id)
    folder.mkdir(parents=True, exist_ok=True)
    rows, saved_paths = [], []
    try:
        for number, photo in enumerate(photos, start=1):
            photo_id = make_id("PHOTO")
            compressed = compress_photo_bytes(photo["bytes"])
            filename = f"{now().strftime('%Y%m%d_%H%M%S')}_{trap_id}_{number:02d}_{photo_id[-4:]}.jpg"
            path = folder / filename
            temp_path = folder / f".{filename}.{uuid.uuid4().hex}.pending"
            temp_path.write_bytes(compressed)
            os.replace(temp_path, path)
            relative = str(path.relative_to(DATA_ROOT).as_posix())
            rows.append([
                photo_id, check_id, window_id, trap_id, site_id, bag_id,
                photo.get("captured_time", dtstr()), photo.get("photo_type", "Other"), relative,
                photo.get("notes", ""),
            ])
            saved_paths.append(path)
        return rows, saved_paths
    except Exception:
        for path in saved_paths:
            path.unlink(missing_ok=True)
        raise


def rollback_photo_files(paths) -> None:
    for path in paths:
        Path(path).unlink(missing_ok=True)


def nav_go(page: str):
    """Navigate from persistent app chrome."""
    go(page)


def human_dt(value, include_year: bool = False, include_seconds: bool = False) -> str:
    parsed = parse_dt(value)
    if not parsed:
        return "—"
    day = parsed.strftime("%d").lstrip("0")
    month = parsed.strftime("%b")
    year = f" {parsed.year}" if include_year else ""
    time_fmt = "%I:%M:%S %p" if include_seconds else "%I:%M %p"
    time_text = parsed.strftime(time_fmt).lstrip("0").lower()
    return f"{day} {month}{year}, {time_text}"


def human_duration(minutes=None, hours=None) -> str:
    """Display elapsed time in the most natural unit without false precision."""
    try:
        total_minutes = float(minutes) if minutes not in (None, "") else float(hours) * 60
    except (TypeError, ValueError):
        return "—"
    if total_minutes < 60:
        return f"{total_minutes:.0f} min"
    total_hours = total_minutes / 60
    if total_hours < 48:
        return f"{total_hours:.1f} hr"
    days = int(total_hours // 24)
    remaining = total_hours - days * 24
    return f"{days} d {remaining:.0f} hr" if remaining >= .5 else f"{days} d"


def trap_has_camera(data, trap_id: str) -> bool:
    rows = data["Traps"][data["Traps"]["Trap ID"] == trap_id]
    return bool(not rows.empty and str(rows.iloc[0].get("Camera ID", "")).strip())


def window_has_camera(data, window) -> bool:
    recorded = str(window.get("Camera Assigned", "")).strip()
    if recorded in ["Yes", "No"]:
        return recorded == "Yes"
    return trap_has_camera(data, str(window.get("Trap ID", "")))


def camera_issue_required(camera_assigned: bool, camera_condition: str, covers: str) -> bool:
    return bool(camera_assigned and (camera_condition != "Working" or covers != "Yes"))


def physical_kill_population(windows: pd.DataFrame) -> pd.DataFrame:
    return windows[windows["Finding At Close"] == "Dead animal found"].copy()


def classify_camera_outcome(is_kill_review, evidence_usable, target, strike_area, activated, assessment):
    if evidence_usable == "No":
        return "Unable to determine"
    if is_kill_review:
        return "Good kill" if assessment == "Humane" else ("Bad kill" if assessment == "Not humane" else "Confirmed kill")
    if target == "No":
        return "No target interaction"
    if target in ["Unclear", "Select…"]:
        return "Unable to determine"
    if strike_area == "No":
        return "Interacted, no meaningful entry"
    if strike_area in ["Unclear", "Select…"]:
        return "Unable to determine"
    if activated == "No":
        return "Entered, no activation"
    if activated in ["Unclear", "Select…"]:
        return "Unable to determine"
    return "Activated, no kill"


def recalculate_window(data, idx: int) -> None:
    """One source of truth for derived timing and validity fields."""
    start_dt = parse_dt(data["Windows"].at[idx, "Start Time"])
    first_dt = parse_dt(data["Windows"].at[idx, "First Interaction Time"])
    trigger_dt = parse_dt(data["Windows"].at[idx, "Trigger Time"])
    kill_dt = parse_dt(data["Windows"].at[idx, "Kill Time"])
    data["Windows"].at[idx, "Time To First Interaction Hr"] = f"{(first_dt-start_dt).total_seconds()/3600:.2f}" if first_dt and start_dt else ""
    data["Windows"].at[idx, "Interaction To Trigger Min"] = f"{(trigger_dt-first_dt).total_seconds()/60:.1f}" if trigger_dt and first_dt and data["Windows"].at[idx, "Activation Evidence"] == "Observed" else ""
    data["Windows"].at[idx, "Interaction To Kill Min"] = f"{(kill_dt-first_dt).total_seconds()/60:.1f}" if kill_dt and first_dt else ""
    data["Windows"].at[idx, "Time To Kill Hr"] = f"{(kill_dt-start_dt).total_seconds()/3600:.2f}" if kill_dt and start_dt else ""
    usable = data["Windows"].at[idx, "Evidence Usable"]
    target = data["Windows"].at[idx, "Target Present"]
    data["Windows"].at[idx, "Valid"] = "Yes" if usable == "Yes" and target in ["Yes", "No"] else "No"



@contextmanager
def app_card():
    """A bordered Streamlit container with an app-owned marker for reliable styling."""
    with st.container(border=True):
        st.markdown(
            '<span class="app-card-marker" aria-hidden="true"></span>',
            unsafe_allow_html=True,
        )
        yield


def workflow_context(rows):
    st.markdown("### Task context")
    with app_card():
        for label, value in rows:
            if value not in (None, ""):
                st.markdown(f"- **{html.escape(str(label))}:** {html.escape(str(value))}")


def saving_update(text: str):
    st.markdown("### Saving this will update")
    st.write(text)


def success_state(title: str, recorded=None, updated=None, next_action=None):
    message_panel("success", title)
    if recorded:
        st.markdown("#### Saved")
        for line in recorded: st.markdown(f"- {line}")
    if updated:
        st.markdown("#### The app updated")
        for line in updated: st.markdown(f"- {line}")
    if next_action:
        st.markdown("#### Next")
        st.write(next_action)


def header(title, subtitle=""):
    st.title(title)
    if subtitle:
        st.markdown(f'<p class="page-context">{subtitle}</p>', unsafe_allow_html=True)


def message_panel(kind: str, title: str, lines=None):
    lines = lines or []
    body = "".join(f"<div class='message-detail'>{line}</div>" for line in lines if line)
    st.markdown(
        f"<div class='message-panel {kind}'><div class='message-title'>{title}</div>{body}</div>",
        unsafe_allow_html=True,
    )


def guidance(message: str):
    message_panel("guidance", message)


def helper(message: str):
    st.markdown(f'<p class="helper-text">{message}</p>', unsafe_allow_html=True)


def set_flash(kind: str, title: str, lines=None):
    st.session_state.flash_message = {"kind": kind, "title": title, "lines": lines or []}


def show_flash():
    flash = st.session_state.pop("flash_message", None)
    if flash:
        message_panel(flash["kind"], flash["title"], flash.get("lines", []))


st.set_page_config(page_title=APP_TITLE, layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

:root {
  color-scheme: light !important;
  --brand-orange: #f36c21;
  --brand-orange-hover: #e9621c;
  --brand-orange-pressed: #cf5515;
  --brand-orange-soft: #fff1e8;
  --text: #25262d;
  --muted: #6f7178;
  --line: #d7d9dd;
  --panel: #f7f7f5;
  --blue-bg: #edf4fb;
  --blue-text: #235f93;
  --green-bg: #eaf7ef;
  --green-text: #22683d;
  --amber-bg: #fff3d9;
  --amber-text: #775900;
  --red-bg: #fff0ea;
  --red-text: #9b3b29;
}

html,
body,
[data-testid="stApp"],
[data-testid="stAppViewContainer"] {
  background: #ffffff !important;
  color: var(--text) !important;
  color-scheme: light !important;
}

html,
body,
[class*="css"],
[data-testid="stAppViewContainer"] {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

h1, h2, h3, h4, h5, h6 {
  font-family: 'Inter', sans-serif !important;
  font-weight: 700 !important;
  letter-spacing: -0.025em;
  color: var(--text) !important;
}
h1 {font-size: clamp(2.2rem, 4vw, 3.6rem) !important; line-height: 1.06 !important; margin-bottom: .45rem !important;}
h2 {font-size: 1.75rem !important; margin-top: 2rem !important;}
h3 {font-size: 1.3rem !important; margin-top: 1.5rem !important;}
p, li, [data-testid="stMarkdownContainer"] {font-size: 1rem; line-height: 1.55;}
.page-context {font-size: 1.05rem; color: var(--muted); margin: 0 0 1.35rem 0;}
.helper-text {font-size: .98rem; color: var(--muted); margin: .35rem 0 1rem 0;}
[data-testid="stWidgetLabel"] p, label p {font-size: 1rem !important; font-weight: 600 !important; color: var(--text) !important;}
[data-testid="stCaptionContainer"] p, .stCaption {font-size: .92rem !important; color: var(--muted) !important;}
[data-testid="stMetricValue"] {font-size: 1.65rem; font-weight: 700; color: var(--text) !important;}
[data-testid="stMetricLabel"] {color: var(--text) !important;}

.block-container {
  max-width: 1220px;
  padding-top: 5.25rem;
  padding-bottom: calc(6rem + env(safe-area-inset-bottom));
}

/* Keep Streamlit system chrome visible. */
header[data-testid="stHeader"] {
  background: #ffffff !important;
  border-bottom: 1px solid #eceef1 !important;
}
header[data-testid="stHeader"] [data-testid="stToolbar"] {
  background: transparent !important;
  overflow: visible !important;
}
header[data-testid="stHeader"] button,
header[data-testid="stHeader"] svg {
  color: var(--text) !important;
  fill: currentColor !important;
}

/* Sidebar navigation. */
[data-testid="stSidebar"] {
  min-width: 230px;
  background: #fafaf8 !important;
}
[data-testid="stSidebar"] [data-testid="stImage"] {margin: .25rem 0 1.25rem 0;}
[data-testid="stSidebar"] > div {
  padding-bottom: calc(7rem + env(safe-area-inset-bottom)) !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label {color: var(--text);}

[data-testid="stSidebar"] button[kind="secondary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {
  background: #ffffff !important;
  border-color: var(--line) !important;
  color: var(--text) !important;
}
[data-testid="stSidebar"] button[kind="secondary"] *,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] * {
  color: var(--text) !important;
}
[data-testid="stSidebar"] button[kind="primary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
  background: var(--brand-orange) !important;
  border-color: var(--brand-orange) !important;
  color: #ffffff !important;
  box-shadow: none !important;
}
[data-testid="stSidebar"] button[kind="primary"] *,
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] * {
  color: #ffffff !important;
}

/* Buttons. */
div.stButton > button,
div.stFormSubmitButton > button,
div.stDownloadButton > button {
  border-radius: 9px;
  font-family: 'Inter', sans-serif;
  font-weight: 700;
  min-height: 2.75rem;
  width: auto;
  padding-left: 1.15rem;
  padding-right: 1.15rem;
}
button[kind="primary"],
[data-testid="stBaseButton-primary"] {
  background: var(--brand-orange) !important;
  border-color: var(--brand-orange) !important;
  color: #ffffff !important;
}
button[kind="primary"] *,
[data-testid="stBaseButton-primary"] * {color: #ffffff !important;}
button[kind="primary"]:hover,
[data-testid="stBaseButton-primary"]:hover {
  background: var(--brand-orange-hover) !important;
  border-color: transparent !important;
  color: #ffffff !important;
}
button[kind="primary"]:active,
[data-testid="stBaseButton-primary"]:active {
  background: var(--brand-orange-pressed) !important;
  border-color: var(--brand-orange-pressed) !important;
}
button[kind="primary"]:focus-visible,
[data-testid="stBaseButton-primary"]:focus-visible {
  outline: 3px solid rgba(243,108,33,.28) !important;
  outline-offset: 2px;
}
button[kind="secondary"],
[data-testid="stBaseButton-secondary"] {
  background: #ffffff !important;
  color: var(--text) !important;
  border-color: var(--line) !important;
}
button[kind="secondary"] *,
[data-testid="stBaseButton-secondary"] * {color: var(--text) !important;}

/* Inputs and forms. */
div[data-baseweb="input"] > div,
div[data-baseweb="textarea"] > div,
div[data-baseweb="select"] > div,
[data-testid="stForm"] {
  background: #ffffff !important;
  color: var(--text) !important;
  border-color: var(--line) !important;
}
input, textarea {
  background: #ffffff !important;
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
  caret-color: var(--text) !important;
}
input::placeholder, textarea::placeholder {
  color: #6a7078 !important;
  opacity: 1 !important;
}
[data-testid="stForm"] {
  border: 1px solid var(--line) !important;
  border-radius: 12px !important;
}
[data-testid="stForm"] div.stFormSubmitButton {margin-top: .35rem;}
[data-testid="stForm"] div.stFormSubmitButton > button {width: auto;}
.element-container:has(div.stButton),
.element-container:has(div.stFormSubmitButton) {margin-top: .35rem;}

/* App-owned marked cards plus Streamlit wrapper fallback. */
.app-card-marker {display: none !important;}
[data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker),
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .app-card-marker),
div[data-testid="stVerticalBlock"]:has(> div.element-container .app-card-marker) {
  background: var(--panel) !important;
  border: 1px solid var(--line) !important;
  box-shadow: none !important;
  border-radius: 14px !important;
}

[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stForm"],
[data-testid="stExpander"],
[data-testid="stFileUploader"],
[data-testid="stCameraInput"],
[data-testid="stDataFrame"],
[data-testid="stTable"] {
  border-color: var(--line) !important;
}
[data-testid="stExpander"],
[data-testid="stFileUploader"],
[data-testid="stCameraInput"] {
  background: var(--panel) !important;
  border: 1px solid var(--line) !important;
  border-radius: 14px !important;
}

/* Metrics are content inside a section card, not another card. */
[data-testid="stMetric"] {
  background: transparent !important;
  border: 0 !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  padding-left: 0 !important;
  padding-right: 0 !important;
}
[data-testid="stDataFrame"] {
  border: 1px solid var(--line) !important;
  border-radius: 10px;
  overflow: hidden;
}

.site-card-title {
  margin-top: 0 !important;
  margin-bottom: .75rem !important;
}

.message-panel {
  border-radius: 12px;
  padding: 1.15rem 1.35rem;
  margin: .65rem 0 1.35rem 0;
  border: 1px solid transparent;
}
.message-panel.guidance {background: var(--blue-bg); color: var(--blue-text); border-color: #d4e7ff;}
.message-panel.success {background: var(--green-bg); color: var(--green-text); border-color: #cfead9;}
.message-panel.warning {background: var(--amber-bg); color: var(--amber-text); border-color: #f2dfaa;}
.message-panel.error {background: var(--red-bg); color: var(--red-text); border-color: #f3cccc;}
.message-title {font-weight: 700; font-size: 1.05rem; line-height: 1.45;}
.message-detail {font-weight: 400; font-size: .96rem; margin-top: .35rem; line-height: 1.45;}
[data-testid="stAlert"] {border-radius: 12px;}
hr {border-color: var(--line);}

.staging-banner {
  background: #fff9c9;
  border: 1px solid #e4d976;
  border-radius: 12px;
  color: var(--text);
  margin: 0 0 1.25rem 0;
  padding: .7rem 1rem;
  line-height: 1.35;
}
.staging-banner, .staging-banner * {color: var(--text) !important;}
.staging-banner-mobile {display: none;}
.staging-banner-desktop {display: inline;}

.field-sticky-header {
  background: rgba(255,255,255,.97);
  border: 1px solid var(--line);
  border-left: 5px solid var(--brand-orange);
  border-radius: 12px;
}
.route-card-current {border-left: 5px solid var(--brand-orange) !important;}

@media (prefers-color-scheme: dark) {
  html,
  body,
  [data-testid="stApp"],
  [data-testid="stAppViewContainer"] {
    background: #ffffff !important;
    color: var(--text) !important;
    color-scheme: light !important;
  }
}

@media (max-width: 700px) {
  .block-container {
    padding-top: 4.25rem;
    padding-left: .85rem;
    padding-right: .85rem;
    padding-bottom: calc(7rem + env(safe-area-inset-bottom));
  }

  h1 {font-size: 1.95rem !important; line-height: 1.05 !important; margin-bottom: .4rem !important;}
  h2 {font-size: 1.4rem !important;}
  h3 {font-size: 1.18rem !important;}

  /* Prevent iOS Safari form-focus auto-zoom. */
  input,
  textarea,
  select,
  [data-baseweb="select"] input {
    font-size: 16px !important;
  }

  .staging-banner {
    margin-bottom: 1rem;
    padding: .55rem .8rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .staging-banner-mobile {display: inline;}
  .staging-banner-desktop {display: none;}

  .message-panel {padding: .9rem 1rem; margin-bottom: 1rem;}

  div.stButton > button,
  div.stFormSubmitButton > button,
  div.stDownloadButton > button {
    width: 100%;
    min-height: 3.1rem;
  }

  .field-sticky-header {
    position: sticky;
    top: .35rem;
    z-index: 999;
    padding: .7rem .85rem;
    margin: -.25rem 0 .8rem 0;
    box-shadow: 0 4px 14px rgba(24,24,27,.08);
    backdrop-filter: blur(6px);
  }
  .field-sticky-header .trap {font-weight: 800; font-size: 1.18rem; line-height: 1.2;}
  .field-sticky-header .meta {font-size: .9rem; color: var(--muted); margin-top: .2rem;}
[data-testid="stSidebar"] > div {
    padding-bottom: calc(7rem + env(safe-area-inset-bottom)) !important;
  }
}

/* v8.6.41 — shared field-control and navigation fixes */
:root {
  --primary-color: #f36c21;
  --st-primary-color: #f36c21;
}

/* App sidebar controls must remain visible on a light header. */
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapseButton"],
button[data-testid="stSidebarCollapsedControl"],
button[data-testid="stSidebarCollapseButton"] {
  color: var(--text) !important;
  background: #ffffff !important;
  opacity: 1 !important;
}
[data-testid="stSidebarCollapsedControl"] svg,
[data-testid="stSidebarCollapseButton"] svg,
button[data-testid="stSidebarCollapsedControl"] svg,
button[data-testid="stSidebarCollapseButton"] svg {
  color: var(--text) !important;
  fill: var(--text) !important;
  stroke: var(--text) !important;
  opacity: 1 !important;
}

/* Radio controls: white unselected surface, orange selected state. */
input[type="radio"] {
  accent-color: var(--brand-orange) !important;
}
label[data-baseweb="radio"] > div:first-child {
  background: #ffffff !important;
  border: 2px solid #444a53 !important;
  box-shadow: none !important;
}
label[data-baseweb="radio"]:has(input:checked) > div:first-child {
  background: #ffffff !important;
  border-color: var(--brand-orange) !important;
}
label[data-baseweb="radio"]:has(input:checked) > div:first-child > div {
  background: var(--brand-orange) !important;
}
label[data-baseweb="radio"] > div:last-child,
label[data-baseweb="radio"] p {
  color: var(--text) !important;
}

/* Select controls: one complete border and consistent light surface. */
div[data-baseweb="select"] > div {
  min-height: 3rem;
  background: #ffffff !important;
  color: var(--text) !important;
  border: 1px solid var(--line) !important;
  border-radius: 10px !important;
  box-shadow: none !important;
  overflow: hidden !important;
}
div[data-baseweb="select"] > div:focus-within {
  border-color: var(--brand-orange) !important;
  box-shadow: 0 0 0 2px rgba(243,108,33,.18) !important;
}
div[data-baseweb="select"] > div > div {
  background: transparent !important;
  color: var(--text) !important;
}
div[data-baseweb="select"] svg {
  color: var(--text) !important;
  fill: var(--text) !important;
}
div[data-baseweb="popover"],
ul[role="listbox"] {
  background: #ffffff !important;
  color: var(--text) !important;
}
li[role="option"] {
  background: #ffffff !important;
  color: var(--text) !important;
}
li[role="option"]:hover,
li[role="option"][aria-selected="true"] {
  background: var(--brand-orange-soft) !important;
  color: var(--text) !important;
}

/* The field CTA follows normal document flow. */
.mobile-save-anchor {
  display: none !important;
}

/* v8.6.43 — final mobile control and navigation visibility */
input[type="checkbox"],
input[type="radio"] {
  accent-color: var(--brand-orange) !important;
}

label[data-baseweb="checkbox"] > div:first-child,
[data-testid="stCheckbox"] label > div:first-child {
  background: #ffffff !important;
  border: 2px solid #444a53 !important;
  box-shadow: none !important;
}
label[data-baseweb="checkbox"]:has(input:checked) > div:first-child,
[data-testid="stCheckbox"] label:has(input:checked) > div:first-child {
  background: var(--brand-orange) !important;
  border-color: var(--brand-orange) !important;
}
label[data-baseweb="checkbox"] svg,
[data-testid="stCheckbox"] svg {
  color: #ffffff !important;
  fill: #ffffff !important;
  stroke: #ffffff !important;
}

[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"],
button[kind="header"],
header button[aria-label*="sidebar" i],
section[data-testid="stSidebar"] button[aria-label*="sidebar" i] {
  background: #ffffff !important;
  color: #202124 !important;
  opacity: 1 !important;
  visibility: visible !important;
  z-index: 1002 !important;
}

[data-testid="stSidebarCollapsedControl"] *,
[data-testid="stSidebarCollapseButton"] *,
[data-testid="collapsedControl"] *,
button[kind="header"] *,
header button[aria-label*="sidebar" i] *,
section[data-testid="stSidebar"] button[aria-label*="sidebar" i] * {
  color: #202124 !important;
  fill: #202124 !important;
  stroke: #202124 !important;
  opacity: 1 !important;
}

@media (max-width: 700px) {
  [data-testid="stSidebarCollapsedControl"],
  [data-testid="stSidebarCollapseButton"],
  [data-testid="collapsedControl"],
  button[kind="header"],
  header button[aria-label*="sidebar" i],
  section[data-testid="stSidebar"] button[aria-label*="sidebar" i] {
    min-width: 2.75rem !important;
    min-height: 2.75rem !important;
  }
}

/* v8.6.50 — Goodnature native visual alignment, adapted for field use */

/* Primary remains orange. Secondary is quiet and neutral. */
button[kind="secondary"],
[data-testid="stBaseButton-secondary"] {
  background: #f3f3f1 !important;
  color: var(--text) !important;
  border-color: transparent !important;
  box-shadow: none !important;
}
button[kind="secondary"]:hover,
[data-testid="stBaseButton-secondary"]:hover {
  background: #ececea !important;
  border-color: transparent !important;
}

/* Tertiary actions may use orange text without a filled surface. */
.tertiary-action button,
button[data-variant="tertiary"] {
  background: transparent !important;
  color: var(--brand-orange) !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

/* Destructive actions are distinct from the normal orange primary action. */
.destructive-action button {
  background: #fff0ea !important;
  color: #9b3b29 !important;
  border-color: #efc9bc !important;
}

/* Section cards: one clear boundary, no heavy nesting. */
[data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker),
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .app-card-marker),
div[data-testid="stVerticalBlock"]:has(> div.element-container .app-card-marker) {
  background: var(--panel) !important;
  border: 1px solid var(--line) !important;
  border-radius: 14px !important;
  box-shadow: 0 2px 10px rgba(37,38,45,.035) !important;
}

/* Semantic panels follow the native app: pale state colour, short message, optional action. */
.message-panel,
[data-testid="stAlert"] {
  border-width: 1px !important;
  box-shadow: none !important;
}
.message-panel.guidance {background: var(--blue-bg); border-color: #d8e6f2;}
.message-panel.success {background: var(--green-bg); border-color: #cfe7d7;}
.message-panel.warning {background: var(--amber-bg); border-color: #ead8a9;}
.message-panel.error {background: var(--red-bg); border-color: #efc9bc;}

/* Keep field labels explicit and readable; do not copy native-app density. */
[data-testid="stWidgetLabel"] p,
label p {
  font-weight: 600 !important;
}

/* Maintain large field tap targets even while visual weight is reduced. */
@media (max-width: 700px) {
  div.stButton > button,
  div.stFormSubmitButton > button,
  div.stDownloadButton > button {
    min-height: 3.1rem;
  }
}

/* v8.6.59 — trap detail history and setup-drawer close control */
.trap-history-day { margin: 1.25rem 0 .45rem; color: var(--text); font-size: .94rem; font-weight: 700; }
.trap-history-day:first-child { margin-top: .25rem; }
.trap-history-event { display: grid; grid-template-columns: 5.25rem minmax(0, 1fr); column-gap: .8rem; align-items: start; padding: .55rem 0; }
.trap-history-time { color: var(--muted); font-size: .82rem; font-variant-numeric: tabular-nums; white-space: nowrap; padding-top: .08rem; }
.trap-history-content { min-width: 0; overflow-wrap: anywhere; }
.trap-history-title { color: var(--text); font-weight: 650; line-height: 1.35; }
.trap-history-details { color: var(--muted); font-size: .88rem; line-height: 1.45; margin-top: .12rem; }
.drawer-close-marker { display: none; }
div[data-testid="stHorizontalBlock"]:has(.drawer-close-marker) { align-items: start; }
div[data-testid="stHorizontalBlock"]:has(.drawer-close-marker) div.stButton > button { min-height: 2.25rem !important; height: 2.25rem !important; width: 2.25rem !important; padding: 0 !important; border-radius: 999px !important; font-size: 1.35rem !important; line-height: 1 !important; background: transparent !important; border-color: transparent !important; color: var(--muted) !important; box-shadow: none !important; }
div[data-testid="stHorizontalBlock"]:has(.drawer-close-marker) div.stButton > button:hover { background: #ececea !important; color: var(--text) !important; }
@media (max-width: 520px) { .trap-history-event { grid-template-columns: 4.6rem minmax(0, 1fr); column-gap: .65rem; } }

/* v8.6.63 — mobile sidebar control must remain visible on the white header. */
@media (max-width: 768px) {
  header[data-testid="stHeader"] [data-testid="stSidebarCollapsedControl"],
  header[data-testid="stHeader"] [data-testid="collapsedControl"],
  header[data-testid="stHeader"] button[aria-label*="sidebar" i],
  header[data-testid="stHeader"] button[aria-label*="menu" i] {
    color: #444a53 !important;
    background: #ffffff !important;
    opacity: 1 !important;
  }

  header[data-testid="stHeader"] [data-testid="stSidebarCollapsedControl"] svg,
  header[data-testid="stHeader"] [data-testid="collapsedControl"] svg,
  header[data-testid="stHeader"] button[aria-label*="sidebar" i] svg,
  header[data-testid="stHeader"] button[aria-label*="menu" i] svg {
    color: #444a53 !important;
    fill: none !important;
    stroke: #444a53 !important;
    opacity: 1 !important;
  }

  header[data-testid="stHeader"] [data-testid="stSidebarCollapsedControl"] svg *,
  header[data-testid="stHeader"] [data-testid="collapsedControl"] svg *,
  header[data-testid="stHeader"] button[aria-label*="sidebar" i] svg *,
  header[data-testid="stHeader"] button[aria-label*="menu" i] svg * {
    color: #444a53 !important;
    stroke: #444a53 !important;
    opacity: 1 !important;
  }
}

/* v8.6.66 — force all mobile navigation chevron geometry to dark grey. */
@media (max-width: 768px) {
  header[data-testid="stHeader"] button,
  [data-testid="stSidebarCollapsedControl"],
  [data-testid="stSidebarCollapseButton"],
  [data-testid="collapsedControl"],
  [data-testid="stSidebar"] details > summary {
    color: #444a53 !important;
  }

  header[data-testid="stHeader"] button svg,
  [data-testid="stSidebarCollapsedControl"] svg,
  [data-testid="stSidebarCollapseButton"] svg,
  [data-testid="collapsedControl"] svg,
  [data-testid="stSidebar"] details > summary svg {
    color: #444a53 !important;
    opacity: 1 !important;
  }

  header[data-testid="stHeader"] button svg path,
  header[data-testid="stHeader"] button svg polyline,
  header[data-testid="stHeader"] button svg line,
  [data-testid="stSidebarCollapsedControl"] svg path,
  [data-testid="stSidebarCollapsedControl"] svg polyline,
  [data-testid="stSidebarCollapsedControl"] svg line,
  [data-testid="stSidebarCollapseButton"] svg path,
  [data-testid="stSidebarCollapseButton"] svg polyline,
  [data-testid="stSidebarCollapseButton"] svg line,
  [data-testid="collapsedControl"] svg path,
  [data-testid="collapsedControl"] svg polyline,
  [data-testid="collapsedControl"] svg line,
  [data-testid="stSidebar"] details > summary svg path,
  [data-testid="stSidebar"] details > summary svg polyline,
  [data-testid="stSidebar"] details > summary svg line {
    stroke: #444a53 !important;
    color: #444a53 !important;
    opacity: 1 !important;
  }

  header[data-testid="stHeader"] button svg path[fill]:not([fill="none"]),
  [data-testid="stSidebarCollapsedControl"] svg path[fill]:not([fill="none"]),
  [data-testid="stSidebarCollapseButton"] svg path[fill]:not([fill="none"]),
  [data-testid="collapsedControl"] svg path[fill]:not([fill="none"]),
  [data-testid="stSidebar"] details > summary svg path[fill]:not([fill="none"]) {
    fill: #444a53 !important;
  }
}

/* v8.6.67 — semantic message text contrast and mobile header clearance. */
.message-panel,
.message-panel *,
[data-testid="stAlert"],
[data-testid="stAlert"] * {
  color: var(--text) !important;
}

.message-panel.warning,
[data-testid="stAlert"][data-baseweb="notification"] {
  color: #4a4317 !important;
}

.message-panel.warning *,
[data-testid="stAlert"][data-baseweb="notification"] * {
  color: #4a4317 !important;
}

/* Keep page-level navigation and context below Streamlit's mobile header. */
@media (max-width: 768px) {
  .block-container {
    padding-top: calc(6.75rem + env(safe-area-inset-top)) !important;
  }

  header[data-testid="stHeader"] {
    min-height: calc(4.25rem + env(safe-area-inset-top)) !important;
  }
}
</style>
""", unsafe_allow_html=True)

require_authentication()
show_environment_banner()
data = load_data()
if "page" not in st.session_state: st.session_state.page = "sites"
if "field_operator" not in st.session_state: st.session_state.field_operator = "Jake"

PRIMARY_NAV = {"Trap sites": "sites", "Traps": "network", "Follow-ups": "followups", "Trial performance": "results"}
SECONDARY_NAV = {"Trial setup": "setup", "Data & records": "data_management"}
WORKFLOW_PAGES = {"site", "visit", "check", "check_confirm"}

# Goodnature wordmark appears once in persistent app chrome.
logo_path = Path(__file__).parent / "goodnature_logo.png"
if logo_path.exists():
    st.sidebar.image(str(logo_path), width=170)

# Primary work stays prominent. Secondary tools sit under More.
if st.session_state.page in WORKFLOW_PAGES:
    st.sidebar.caption("Visit workflow")
    if st.session_state.page in {"visit", "check", "check_confirm"}:
        sid = st.session_state.get("site_id", "")
        vid = st.session_state.get("visit_id", "")
        if sid:
            st.sidebar.write(f"**{site_name(data, sid)}**")
        if vid:
            st.sidebar.caption(f"Visit {vid}")
    if st.sidebar.button("Exit to Trap sites"):
        nav_go("sites")
else:
    st.sidebar.caption("Main")
    for label, target in PRIMARY_NAV.items():
        is_active = (
            st.session_state.page == target
            or (target == "network" and st.session_state.page == "trap_detail")
        )
        if st.sidebar.button(
            label,
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            nav_go(target)
    with st.sidebar.expander("Administration", expanded=st.session_state.page in SECONDARY_NAV.values()):
        for label, target in SECONDARY_NAV.items():
            if st.button(label, key=f"nav_{target}", use_container_width=True, type="primary" if st.session_state.page == target else "secondary"):
                nav_go(target)


# Close the mobile menu from the same tap that selects a destination.
components.html(
    """
    <script>
    (() => {
      const parent = window.parent;
      const doc = parent.document;
      const listenerKey = '__r1m1MobileNavCloseInstalled';

      if (parent[listenerKey]) return;
      parent[listenerKey] = true;

      const destinationLabels = new Set([
        'Trap sites',
        'Traps',
        'Follow-ups',
        'Trial performance',
        'Trial setup',
        'Data & records'
      ]);

      const sidebarIsOpen = () => {
        const sidebar = doc.querySelector('[data-testid="stSidebar"]');
        if (!sidebar) return false;
        const rect = sidebar.getBoundingClientRect();
        const style = parent.getComputedStyle(sidebar);
        return (
          sidebar.getAttribute('aria-hidden') !== 'true' &&
          style.display !== 'none' &&
          style.visibility !== 'hidden' &&
          rect.width > 20 &&
          rect.left < parent.innerWidth &&
          rect.right > 0
        );
      };

      const collapseControl = () => {
        const selectors = [
          '[data-testid="stSidebarCollapseButton"] button',
          '[data-testid="stSidebarCollapseButton"]',
          'button[aria-label="Close sidebar"]',
          'button[aria-label="Collapse sidebar"]',
          'button[aria-label*="close" i][aria-label*="sidebar" i]',
          'button[aria-label*="collapse" i][aria-label*="sidebar" i]'
        ];
        for (const selector of selectors) {
          const node = doc.querySelector(selector);
          if (!node) continue;
          return node.matches('button, [role="button"]')
            ? node
            : node.querySelector('button, [role="button"]') || node;
        }
        return null;
      };

      doc.addEventListener(
        'click',
        (event) => {
          if (parent.innerWidth > 768 || !sidebarIsOpen()) return;
          const button = event.target.closest('[data-testid="stSidebar"] button');
          if (!button) return;
          const label = (button.innerText || button.textContent || '').trim();
          if (!destinationLabels.has(label)) return;
          const control = collapseControl();
          if (control && control !== button) control.click();
        },
        true
      );
    })();
    </script>
    """,
    height=0,
    width=0,
)

page = st.session_state.page
scroll_to_top_once()
show_flash()

is_demo_data = any(data[name].astype(str).apply(lambda col: col.str.contains("synthetic|sample", case=False, na=False)).any().any() for name in ["Sites", "Windows"] if not data[name].empty)
if is_demo_data:
    message_panel("warning", "Demo data", ["This app contains synthetic demonstration records. Do not treat its Performance figures as trial evidence."])

if page == "sites":
    header("Trap sites", "Choose the trap site you are visiting today.")
    for _, s in data["Sites"].iterrows():
        sid = s["Site ID"]
        traps = data["Traps"][(data["Traps"]["Site ID"] == sid) & (data["Traps"]["Status"] == "Active")]
        active = active_visit(data, sid); last = latest_completed_visit(data, sid)
        interval = int(float(s["Visit Interval Days"] or 3)); last_dt = parse_dt(last["End Time"]) if last is not None else None
        next_dt = last_dt + timedelta(days=interval) if last_dt else now()
        with app_card():
            st.markdown(
                f'<h3 class="site-card-title">{html.escape(str(s["Site Name"]))}</h3>',
                unsafe_allow_html=True,
            )
            st.caption(f"{len(traps)} active traps · Visit every {interval} days")
            st.write(f"Last completed: **{last_dt.strftime('%d %b %Y') if last_dt else 'No completed visit yet'}**")
            st.write(f"Next visit: **{'Due now' if next_dt.date() <= now().date() else next_dt.strftime('%d %b %Y')}**")
            if active is not None:
                checks = data["Checks"][data["Checks"]["Visit ID"] == active["Visit ID"]]
                st.caption(f"Visit in progress · {len(checks)} of {len(traps)} checked")
                if st.button("Resume checking", key=f"resume_{sid}", type="primary"):
                    go("visit", site_id=sid, visit_id=active["Visit ID"])
            else:
                if st.button("Start checking", key=f"open_{sid}", type="primary"):
                    vid = start_visit_now(data, sid, st.session_state.field_operator)
                    go("visit", site_id=sid, visit_id=vid)

elif page == "site":
    sid = st.session_state.site_id; s = data["Sites"][data["Sites"]["Site ID"] == sid].iloc[0]
    if st.button("← Trap sites"): go("sites")
    traps = data["Traps"][(data["Traps"]["Site ID"] == sid) & (data["Traps"]["Status"] == "Active")].copy()
    traps["_order"] = pd.to_numeric(traps["Route Order"], errors="coerce"); traps = traps.sort_values("_order")
    header(s["Site Name"], f"{len(traps)} traps")
    with st.expander("Visit details", expanded=False):
        st.session_state.field_operator = st.text_input("Operator", value=st.session_state.field_operator, key="site_operator")
        st.caption("The visit date and start time are recorded automatically when checking begins.")
    if st.button("Start checking traps", type="primary"):
        active = active_visit(data, sid)
        vid = active["Visit ID"] if active is not None else start_visit_now(data, sid, st.session_state.field_operator)
        go("visit", site_id=sid, visit_id=vid)
    st.markdown("### Traps")
    for _, tr in traps.iterrows():
        with app_card():
            c1,c2 = st.columns([.22,1], vertical_alignment="center")
            c1.markdown(f"**{int(float(tr['Route Order'])) if str(tr['Route Order']).strip() else '—'}**")
            c2.markdown(f"**{tr['Trap ID']}**")
            c2.caption(trap_location_label(tr))

elif page == "start_visit":
    sid = st.session_state.site_id
    vid = start_visit_now(data, sid, st.session_state.field_operator)
    go("visit", site_id=sid, visit_id=vid)

elif page == "visit":
    sid = st.session_state.site_id; vid = st.session_state.visit_id
    visit_rows = data["Visits"][data["Visits"]["Visit ID"] == vid]
    if visit_rows.empty:
        message_panel("error", "This visit could not be found.", ["Return to Trap sites and start again."])
        if st.button("Back to Trap sites"): go("sites")
        st.stop()
    visit = visit_rows.iloc[0]
    traps = data["Traps"][(data["Traps"]["Site ID"] == sid) & (data["Traps"]["Status"] == "Active")].copy()
    traps["_order"] = pd.to_numeric(traps["Route Order"], errors="coerce"); traps = traps.sort_values("_order")
    checks = data["Checks"][data["Checks"]["Visit ID"] == vid]; done = set(checks["Trap ID"])
    remaining=[x for x in traps["Trap ID"] if x not in done]
    saved = st.session_state.pop("saved_check", None)
    header(site_name(data,sid), "")
    if saved:
        task_text = saved.get("task_text", "")
        consequence_text = task_text
        if saved.get("new_window"):
            consequence_text = (consequence_text + " " if consequence_text else "") + "New test window started."
        elif saved.get("assessable"):
            consequence_text = (consequence_text + " " if consequence_text else "") + "No new test window started."
        if remaining:
            nxt = trap_row(data, remaining[0])
            success_state(
                "Check saved",
                recorded=[f"{saved['trap_id']} · {len(done)} of {len(traps)} complete"],
                updated=[consequence_text] if consequence_text else [],
                next_action=f"{remaining[0]} · {trap_location_label(nxt)}",
            )
            st.button(
                "Check next trap",
                type="primary",
                key="success_next_trap",
                on_click=set_page,
                args=("check",),
                kwargs={"site_id": sid, "visit_id": vid, "trap_id": remaining[0]},
            )
        else:
            message_panel(
                "success",
                "Site check complete",
                [f"{len(done)} of {len(traps)} traps checked", consequence_text],
            )
            if st.button("Finish site check", type="primary", key="success_finish_site"):
                idx=data["Visits"].index[data["Visits"]["Visit ID"]==vid][0]
                data["Visits"].at[idx,"End Time"]=dtstr(); data["Visits"].at[idx,"Status"]="Complete"; save_data(data)
                go("sites")
    else:
        st.progress(len(done)/max(len(traps),1), text=f"{len(done)} of {len(traps)} complete")
        if remaining:
            next_trap = remaining[0]; tr=trap_row(data,next_trap)
            is_first = len(done) == 0
            with app_card():
                st.caption("FIRST TRAP" if is_first else "NEXT TRAP")
                st.subheader(next_trap)
                st.write(trap_location_label(tr))
                st.caption(f"Trap {tr['Route Order']} · {tr['Build Version']}")
                if st.button("Check trap" if is_first else "Check next trap", type="primary"):
                    go("check", site_id=sid, visit_id=vid, trap_id=next_trap)
            with st.expander("Choose another trap"):
                st.caption("Use this only when you need to check a different trap next.")
                other = st.selectbox("Trap", remaining, format_func=lambda x: f"{x} — {trap_location_label(trap_row(data, x))}")
                if st.button("Check selected trap"): go("check", site_id=sid, visit_id=vid, trap_id=other)
        else:
            message_panel("success", "Every trap has been accounted for.", ["Finish the site when you are ready to leave."])
            if st.button("Finish site check", type="primary"):
                idx=data["Visits"].index[data["Visits"]["Visit ID"]==vid][0]
                data["Visits"].at[idx,"End Time"]=dtstr(); data["Visits"].at[idx,"Status"]="Complete"; save_data(data)
                go("sites")
    with st.expander(f"View trap progress · {len(done)} of {len(traps)} complete", expanded=False):
        for _, tr in traps.iterrows():
            trap_id = tr["Trap ID"]
            status = "Checked" if trap_id in done else ("Next" if remaining and trap_id == remaining[0] else "Remaining")
            css = "route-card-current" if status == "Next" else ""
            st.markdown(f'<div class="{css}"></div>', unsafe_allow_html=True)
            with app_card():
                cols=st.columns([.22,1,.42], vertical_alignment="center")
                cols[0].markdown(f"**{int(float(tr['Route Order'])) if str(tr['Route Order']).strip() else '—'}**")
                cols[1].markdown(f"**{trap_id}**"); cols[1].caption(trap_location_label(tr))
                cols[2].write("✓" if status == "Checked" else status)
    if remaining and st.button("Pause and return to Trap sites"):
        go("sites")

elif page == "check":
    sid,vid,trap_id=st.session_state.site_id,st.session_state.visit_id,st.session_state.trap_id
    tr=trap_row(data,trap_id); w=open_window(data,trap_id)
    traps = data["Traps"][(data["Traps"]["Site ID"] == sid) & (data["Traps"]["Status"] == "Active")].copy()
    traps["_order"] = pd.to_numeric(traps["Route Order"], errors="coerce"); traps = traps.sort_values("_order")
    done = set(data["Checks"][data["Checks"]["Visit ID"] == vid]["Trap ID"])
    total_traps = len(traps)
    route_number = int(float(tr["Route Order"])) if str(tr["Route Order"]).strip() else "—"
    progress_number = len(done) + (0 if trap_id in done else 1)
    st.markdown(
        f'<div class="field-sticky-header"><div class="trap">{html.escape(str(trap_id))}</div>'
        f'<div class="meta">Trap {progress_number} of {total_traps} · {html.escape(site_name(data,sid))}<br>{html.escape(trap_location_label(tr))}</div></div>',
        unsafe_allow_html=True,
    )
    if st.button("← Back to traps"): go("visit",site_id=sid,visit_id=vid)
    if w is None:
        message_panel("error", "This trap has no active test window.", ["Do not record a check until the missing window has been resolved in Trial history or Setup."])
        st.stop()
    st.caption(f"Current window · {tr['Build Version']} · started {human_dt(w['Start Time'])}")
    with app_card():
        st.markdown("### 1. What did you find?")
        finding=st.radio("Choose the closest match",FINDINGS, index=None, label_visibility="collapsed", key=f"finding_{trap_id}_{vid}")
        if finding is None:
            st.caption("Choose one finding to continue.")
            st.stop()
        bag_id=""; has_animal = finding == "Dead animal found"
        if has_animal:
            bag_key=f"bag_id_{vid}_{trap_id}"
            if bag_key not in st.session_state: st.session_state[bag_key]=next_bag_id(data,sid)
            bag_id=st.session_state[bag_key]
            message_panel("warning", f"Write {bag_id} on the bag now.", ["Bag and label the animal before continuing."])
        species=""; rat_type=""; condition=""; animal_bagged=False; next_step=2
        if has_animal:
            st.markdown(f"### {next_step}. Record and clear the animal"); next_step += 1
            species=st.selectbox("Species",SPECIES,index=None,placeholder="Choose species",key=f"species_{trap_id}_{vid}")
            rat_type=st.selectbox("Rat type",RAT_TYPES,index=None,placeholder="Choose rat type",key=f"rat_type_{trap_id}_{vid}") if species=="Rat" else ""
            condition=st.selectbox("Animal condition when found",ANIMAL_CONDITION,index=None,placeholder="Choose observed condition",help="Record what you can physically see. This is not the final humane-kill conclusion.",key=f"condition_{trap_id}_{vid}")
            animal_bagged=st.checkbox(f"Animal bagged and labelled {bag_id}",key=f"bagged_{trap_id}_{vid}")

            st.markdown("#### Photograph the animal")
            st.caption("Add a clear photo before removing the animal. Include the head and ears where possible. Photos are linked to this check and bag ID.")
            render_check_photo_capture(vid, trap_id)
        elif finding=="Trap fired, no animal":
            st.warning("Camera review will determine whether this was a missed kill, false activation or non-target event.")
        elif finding in ["Trap missing", "Unable to check"]:
            st.warning("This window will close as not assessable and no new window will start.")
        st.markdown(f"### {next_step}. Service the trap"); next_step += 1
        inspectable = finding not in ["Trap missing", "Unable to check"]
        if inspectable:
            lure=st.selectbox("Lure condition found",LURE,index=None,placeholder="Choose lure condition",key=f"lure_{trap_id}_{vid}")
            relure_choice=st.radio("Fresh lure added?",["Yes","No"],index=None,horizontal=True,key=f"relured_{trap_id}_{vid}")
            relured = relure_choice == "Yes"
            trap_state_options = (["Fired and reset", "Not ready / could not reset", "Could not assess"]
                                  if finding in ["Dead animal found", "Trap fired, no animal"]
                                  else ["Still set and ready", "Fired and reset", "Not ready / could not reset", "Could not assess"])
            trap_state=st.radio(
                "How was the trap left?",
                trap_state_options,
                index=None,
                key=f"trap_state_{trap_id}_{vid}",
                help="Choose what actually happened. Firing and resetting is not required when reluring if the trap remained set and ready.",
            )
            readiness = "Yes" if trap_state in ["Still set and ready", "Fired and reset"] else ("No" if trap_state == "Not ready / could not reset" else "Could not assess" if trap_state else None)
        else:
            lure=""; relure_choice="Not applicable"; relured=False; trap_state="Could not assess"; readiness="Could not assess"
            st.caption("Lure and trap readiness cannot be confirmed for this finding.")
        site_condition=st.selectbox("Site condition",["Normal","Disturbed","Other"],index=None,placeholder="Choose site condition",key=f"site_condition_{trap_id}_{vid}")
        camera_assigned = bool(str(tr.get("Camera ID", "")).strip())
        if camera_assigned:
            st.markdown(f"### {next_step}. Check the camera")
            camera_ready_choice=st.radio("Camera ready and covering the trap?",["Yes","No","Could not assess"],index=None,key=f"camera_ready_{trap_id}_{vid}")
            if camera_ready_choice == "No":
                camera=st.selectbox("Camera issue",[x for x in CAMERA if x != "Working"],index=None,placeholder="Choose camera issue",key=f"camera_issue_{trap_id}_{vid}")
                covers=st.selectbox("Camera still covers trap",["No","Unsure","Yes"],index=None,placeholder="Choose coverage status",key=f"covers_{trap_id}_{vid}")
                adjusted=st.checkbox("Camera adjusted",key=f"adjusted_{trap_id}_{vid}")
            elif camera_ready_choice == "Yes":
                camera="Working"; covers="Yes"; adjusted=False
            else:
                camera="Unsure"; covers="Unsure"; adjusted=False
        else:
            camera_ready_choice="Not applicable"; camera="No camera"; covers="Not applicable"; adjusted=False
            st.caption("No camera is assigned to this trap. Camera review is not required.")
        notes=st.text_area("Anything else to record?",height=72,key=f"notes_{trap_id}_{vid}")
        change_time=st.toggle("Change check time",value=False,key=f"change_time_{trap_id}_{vid}")
        if change_time:
            c1,c2=st.columns(2); d=c1.date_input("Check date",value=now().date(),key=f"check_date_{trap_id}_{vid}"); tm=c2.time_input("Check time",value=now().time(),key=f"check_time_{trap_id}_{vid}")
        else:
            d=None; tm=None
        submitted=st.button("Review check",type="primary",key=f"review_check_{trap_id}_{vid}")
    if submitted:
        errors=[]
        if finding=="Dead animal found" and not species: errors.append("Choose the species found.")
        if finding=="Dead animal found" and species=="Rat" and not rat_type: errors.append("Choose Norway rat, Ship rat or Unclear.")
        if finding=="Dead animal found" and not condition: errors.append("Choose the animal condition observed.")
        if finding=="Dead animal found" and not animal_bagged: errors.append(f"Bag and label the animal **{bag_id}**, then confirm it above.")
        if inspectable and not lure: errors.append("Choose the lure condition found.")
        if inspectable and relure_choice is None: errors.append("Confirm whether fresh lure was added.")
        if inspectable and trap_state is None: errors.append("Choose how the trap was left.")
        if inspectable and readiness in ["No","Could not assess"] and not notes.strip(): errors.append("Add a note explaining why the trap was not confirmed ready.")
        if not site_condition: errors.append("Choose the site condition.")
        if camera_assigned and camera_ready_choice is None: errors.append("Confirm whether the camera is ready and covering the trap.")
        if camera_assigned and camera_ready_choice == "No" and not camera: errors.append("Choose the camera issue.")
        if camera_assigned and camera_ready_choice == "No" and not covers: errors.append("Choose whether the camera still covers the trap.")
        if errors:
            message_panel("error","Complete the highlighted check details.",errors)
        else:
            check_time=datetime.combine(d,tm).replace(microsecond=0) if change_time else now()
            if trap_state in ["Still set and ready", "Fired and reset"]:
                ready=True
                trap_function="Tested and working" if trap_state == "Fired and reset" else "Not function-tested"
            elif trap_state == "Not ready / could not reset":
                ready=False; trap_function="No"
            else:
                trap_state="Not assessed"; ready=False; trap_function="Unsure"
            photos = st.session_state.get(photo_session_key(vid, trap_id), []) if has_animal else []
            st.session_state.pending_check={"check_time":check_time,"finding":finding,"species":species,"rat_type":rat_type,"condition":condition,"bag_id":bag_id,"animal_bagged":animal_bagged,"lure":lure,"relured":relured,"trap_state":trap_state,"ready":ready,"trap_function":trap_function,"site_condition":site_condition,"camera":camera,"covers":covers,"adjusted":adjusted,"notes":notes,"photo_count":len(photos)}
            go("check_confirm", site_id=sid, visit_id=vid, trap_id=trap_id)

elif page == "check_confirm":
    sid,vid,trap_id=st.session_state.site_id,st.session_state.visit_id,st.session_state.trap_id; p=st.session_state.pending_check
    tr=trap_row(data,trap_id); bag_id=p.get("bag_id","")
    camera_assigned = bool(str(tr.get("Camera ID", "")).strip())
    camera_ready = (not camera_assigned) or (p["camera"] == "Working" and p["covers"] == "Yes")
    assessable = p["finding"] not in ["Trap missing", "Unable to check"]
    will_start = bool(p["relured"] and p["ready"] and camera_ready and assessable)
    st.button("← Edit check", on_click=set_page, args=("check",), kwargs={"site_id": sid, "visit_id": vid, "trap_id": trap_id})
    header("Confirm check", f"{trap_id} · {trap_location_label(tr)}")

    st.markdown("### You recorded")
    with app_card():
        st.markdown(f"- **Finding:** {p['finding']}")
        st.markdown(f"- **Trap condition:** {p['trap_state']}")
        st.markdown(f"- **Fresh lure added:** {'Yes' if p.get('relured') else 'No'}")
        if bag_id:
            st.markdown(f"- **Bag labelled:** {bag_id}")
        if p.get("photo_count", 0):
            st.markdown(f"- **Photos ready to save:** {p['photo_count']}")
        camera_summary = ("No camera assigned" if not camera_assigned else ("Working and covering the trap" if camera_ready else "Issue recorded"))
        st.markdown(f"- **Camera:** {camera_summary}")
        if p.get("site_condition") and p["site_condition"] != "Normal":
            st.markdown(f"- **Site condition:** {p['site_condition']}")

    st.markdown("### After saving, the app will")
    with app_card():
        st.markdown("- Close the current test window at the recorded check time")
        if assessable and camera_assigned:
            st.markdown("- Create a camera review task linked to this trap and test window")
        if p["finding"] == "Dead animal found":
            st.markdown("- Create a necropsy review task linked to the bag ID")
        camera_issue = camera_issue_required(camera_assigned, p["camera"], p["covers"])
        if camera_issue:
            st.markdown("- Create a camera-issue task")
        if will_start:
            st.markdown("- Start a new test window")
        else:
            reasons=[]
            if not p["relured"]: reasons.append("fresh lure was not added")
            if not p["ready"]: reasons.append("the trap was not confirmed ready")
            if camera_assigned and not camera_ready: reasons.append("the camera was not confirmed working and covering the trap")
            if not assessable: reasons.append("the trap was not assessable")
            st.markdown("- **Not** start a new test window")
            st.caption("Reason: " + ", ".join(reasons) + ".")

    st.markdown("### Next")
    st.write("Save this check, then continue to the next trap.")
    if st.button("Save check",type="primary"):
        active=open_window(data,trap_id)
        if active is None:
            st.error("Save blocked: this trap no longer has an active window. Return to the line and resolve the window before trying again.")
        else:
            old_id=close_window(data,trap_id,p["check_time"],p["finding"],bag_id)
            new_id=start_window(data,trap_id,p["check_time"]) if will_start else ""
            reset_required = p["trap_state"] in ["Fired and reset", "Not ready / could not reset"]
            reset_done = p["trap_state"] == "Fired and reset"
            idxs=data["Windows"].index[data["Windows"]["Window ID"]==old_id].tolist()
            if idxs:
                data["Windows"].at[idxs[0],"Species"]=p.get("species","")
                data["Windows"].at[idxs[0],"Rat Type"]=p.get("rat_type","")
            check_id = make_id("CHK")
            row=[check_id,vid,trap_id,old_id,dtstr(p["check_time"]),p["finding"],p["species"],p.get("rat_type",""),p["condition"],bag_id,"Yes" if bag_id else "No","Yes" if p.get("animal_bagged") else "No",p["lure"],"Yes" if p["relured"] else "No","Yes" if reset_required else "No","Yes" if reset_done else "No","Yes" if p["ready"] else "No",p["trap_function"],p["site_condition"],p["camera"],p["covers"],"Yes" if p["adjusted"] else "No",new_id,p["notes"]]
            data["Checks"]=pd.concat([data["Checks"],pd.DataFrame([row],columns=SHEETS["Checks"])],ignore_index=True)
            photos = st.session_state.get(photo_session_key(vid, trap_id), [])
            prepared_photo_rows = []
            saved_photo_files = []
            if assessable and camera_assigned:
                priority="High" if p["finding"]=="Trap fired, no animal" else "Normal"
                add_followup(data,"Camera review",sid,trap_id,vid,old_id,bag_id,p["finding"],"Confirm whether target interaction occurred, its level, first interaction time, strike-area entry, activation, kill and video evidence",priority)
            if p["finding"]=="Dead animal found":
                add_followup(data,"Necropsy review",sid,trap_id,vid,old_id,bag_id,"Dead animal collected","Add necropsy result, weight range, measurements and final humane-kill conclusion","Normal")
            camera_issue = camera_issue_required(camera_assigned, p["camera"], p["covers"])
            if camera_issue:
                add_followup(data,"Camera issue",sid,trap_id,vid,old_id,bag_id,"Camera issue","Resolve camera condition and record the evidence gap","High")
            refresh_review_status(data,old_id)
            photos_before = data["Photos"].copy()
            try:
                prepared_photo_rows, saved_photo_files = prepare_check_photos(photos, check_id, old_id, trap_id, sid, bag_id)
                if prepared_photo_rows:
                    data["Photos"] = pd.concat([data["Photos"], pd.DataFrame(prepared_photo_rows, columns=SHEETS["Photos"])], ignore_index=True)
                save_data(data)
            except Exception as exc:
                rollback_photo_files(saved_photo_files)
                data["Photos"] = photos_before
                st.error(f"Save failed. No photos or trap-check data were committed: {exc}")
                st.stop()
            st.session_state.pop("pending_check",None)
            st.session_state.pop(f"bag_id_{vid}_{trap_id}",None)
            st.session_state.pop(photo_session_key(vid, trap_id), None)
            st.session_state.pop(photo_capture_mode_key(vid, trap_id), None)
            st.session_state.pop(photo_widget_nonce_key(vid, trap_id), None)
            st.session_state.pop(f"photo_feedback_{vid}_{trap_id}", None)
            created_tasks=[]
            if assessable and camera_assigned: created_tasks.append("Camera review")
            if p["finding"]=="Dead animal found": created_tasks.append("necropsy task")
            if camera_issue: created_tasks.append("camera-issue task")
            if not created_tasks:
                task_text="No follow-up tasks required."
            elif len(created_tasks)==1:
                task_text=f"{created_tasks[0][0].upper() + created_tasks[0][1:]} created."
            else:
                task_text=f"{', '.join(created_tasks[:-1])} and {created_tasks[-1]} created."
                task_text=task_text[0].upper()+task_text[1:]
            if saved_photo_files:
                task_text = (task_text + " " if task_text else "") + f"{len(saved_photo_files)} photo{'s' if len(saved_photo_files) != 1 else ''} saved."
            st.session_state.saved_check={"trap_id":trap_id,"task_text":task_text,"new_window":will_start,"assessable":assessable}
            go("visit",site_id=sid,visit_id=vid)

elif page == "network":
    header("Traps", "Find a trap and review its kills, checks and full history.")

    filter_col, search_col = st.columns([1, 1.5])

    site_options = ["All sites"] + data["Sites"]["Site ID"].tolist()
    saved_site_filter = st.session_state.get(
        "traps_site_filter_value", "All sites"
    )
    if saved_site_filter not in site_options:
        saved_site_filter = "All sites"

    site_filter = filter_col.selectbox(
        "Site",
        site_options,
        index=site_options.index(saved_site_filter),
        format_func=lambda x: x if x == "All sites" else site_name(data, x),
        key="traps_site_filter_widget",
    )
    st.session_state.traps_site_filter_value = site_filter

    search_value = search_col.text_input(
        "Find trap",
        value=st.session_state.get("traps_search_value", ""),
        placeholder="Trap ID or location",
        key="traps_search_widget",
    )
    st.session_state.traps_search_value = search_value
    search_text = search_value.strip().lower()

    traps = data["Traps"].copy()
    if site_filter != "All sites":
        traps = traps[traps["Site ID"] == site_filter]
    if search_text:
        traps = traps[
            traps.apply(
                lambda row: search_text in str(row["Trap ID"]).lower()
                or search_text in trap_location_label(row).lower(),
                axis=1,
            )
        ]

    if traps.empty:
        helper("No traps match this filter.")
    else:
        st.caption("Open a trap to see every recorded check and follow-up.")
        traps = traps.assign(
            _route_num=pd.to_numeric(traps["Route Order"], errors="coerce")
        )
        for _, tr in traps.sort_values(["Site ID", "_route_num"]).iterrows():
            trap_id = tr["Trap ID"]
            trap_checks = data["Checks"][
                data["Checks"]["Trap ID"].astype(str) == str(trap_id)
            ].copy()
            kills = trap_checks[
                trap_checks["Finding"].astype(str) == "Dead animal found"
            ]
            last_kill = (
                human_dt(kills.iloc[-1]["Check Time"])
                if not kills.empty
                else "No kills recorded"
            )

            with app_card():
                c1, c2, c3, action = st.columns(
                    [1.25, 1.35, 1.25, 0.72],
                    vertical_alignment="center",
                )
                c1.markdown(f"**{trap_id}**")
                c1.caption(site_name(data, tr["Site ID"]))

                c2.write(trap_location_label(tr))
                c2.caption(f"Trap {tr['Route Order']} · {tr['Build Version']}")

                c3.markdown(
                    f"**{len(kills)} kill{'s' if len(kills) != 1 else ''}**"
                )
                c3.caption(
                    f"{len(trap_checks)} check{'s' if len(trap_checks) != 1 else ''} · "
                    f"Last kill: {last_kill}"
                )

                if action.button(
                    "View",
                    key=f"network_view_{trap_id}",
                    use_container_width=True,
                ):
                    go("trap_detail", trap_id=trap_id)

elif page == "trap_detail":
    trap_id = st.session_state.get("trap_id", "")
    matches = data["Traps"][
        data["Traps"]["Trap ID"].astype(str) == str(trap_id)
    ]

    if matches.empty:
        message_panel(
            "error",
            "This trap could not be found.",
            ["Return to Traps and choose another record."],
        )
        if st.button("Back to traps"):
            go("network")
        st.stop()

    tr = matches.iloc[0]
    trap_checks = data["Checks"][
        data["Checks"]["Trap ID"].astype(str) == str(trap_id)
    ].copy()
    kills = trap_checks[
        trap_checks["Finding"].astype(str) == "Dead animal found"
    ].copy()
    completed_followups = data["Followups"][
        (data["Followups"]["Trap ID"].astype(str) == str(trap_id))
        & (data["Followups"]["Status"] == "Complete")
    ].copy()

    if st.button("← Back to traps", key="back_to_traps"):
        go("network")

    header(
        trap_id,
        f"{site_name(data, tr['Site ID'])} · {trap_location_label(tr)} · "
        f"{tr['Build Version']}",
    )

    kill_col, check_col, last_col = st.columns(3)
    kill_col.metric("Kills", len(kills))
    check_col.metric("Checks", len(trap_checks))
    last_col.metric(
        "Last kill",
        human_dt(kills.iloc[-1]["Check Time"]) if not kills.empty else "—",
    )

    w = open_window(data, trap_id)
    st.caption(
        f"Current test window: {w['Window ID'] if w is not None else 'None'}"
    )

    st.divider()
    st.markdown("### Full history")

    events = []
    for _, check in trap_checks.iterrows():
        finding = check["Finding"] or "Check recorded"
        details = []
        if check["Species"]:
            details.append(str(check["Species"]))
        if check["Bag ID"]:
            details.append(f"Bag {check['Bag ID']}")
        if check["Lure Condition"]:
            details.append(f"Lure: {check['Lure Condition']}")
        if check.get("Trap Ready After Check", ""):
            details.append(f"Trap ready: {check['Trap Ready After Check']}")
        if check["Notes"]:
            details.append(str(check["Notes"]))

        events.append(
            (
                parse_dt(check["Check Time"]),
                finding,
                " · ".join(details) if details else "No additional notes.",
            )
        )

    for _, followup in completed_followups.iterrows():
        events.append(
            (
                parse_dt(followup["Completed Time"]),
                followup["Follow-up Type"],
                followup["Notes"] or "Follow-up completed.",
            )
        )

    events = sorted(
        events,
        key=lambda event: event[0] or datetime.min,
        reverse=True,
    )

    if not events:
        helper("No history has been recorded for this trap yet.")
    else:
        grouped_events = {}
        for when, title, details in events:
            day_key = when.date() if when else None
            grouped_events.setdefault(day_key, []).append((when, title, details))

        today = now().date()
        yesterday = today - timedelta(days=1)
        for day_key, day_events in grouped_events.items():
            if day_key is None:
                day_heading = "Unknown date"
            elif day_key == today:
                day_heading = f"Today — {day_key.strftime('%-d %B %Y')}"
            elif day_key == yesterday:
                day_heading = f"Yesterday — {day_key.strftime('%-d %B %Y')}"
            else:
                day_heading = day_key.strftime("%-d %B %Y")

            st.markdown(
                f'<div class="trap-history-day">{html.escape(day_heading)}</div>',
                unsafe_allow_html=True,
            )
            for when, title, details in day_events:
                time_text = when.strftime("%-I:%M %p").lower() if when else "—"
                st.markdown(
                    '<div class="trap-history-event">'
                    f'<div class="trap-history-time">{html.escape(time_text)}</div>'
                    '<div class="trap-history-content">'
                    f'<div class="trap-history-title">{html.escape(str(title))}</div>'
                    f'<div class="trap-history-details">{html.escape(str(details))}</div>'
                    '</div></div>',
                    unsafe_allow_html=True,
                )

elif page == "followups":
    header("Follow-ups", "Complete tasks created during trap checks.")
    fu=data["Followups"][data["Followups"]["Status"]=="Open"].copy()
    selected_followup_id=st.session_state.get("followup_panel")

    if not selected_followup_id:
        filter_left,action_right=st.columns([4,1],vertical_alignment="bottom")
        with filter_left:
            filter_site,filter_priority=st.columns(2)
            followup_site=filter_site.selectbox("Site",["All sites"]+data["Sites"]["Site ID"].tolist(),format_func=lambda x:x if x=="All sites" else site_name(data,x),key="followup_site_filter")
            followup_priority=filter_priority.selectbox("Priority",["All priorities","High","Normal","Low"],key="followup_priority_filter")
        if followup_site!="All sites": fu=fu[fu["Site ID"]==followup_site]
        if followup_priority!="All priorities": fu=fu[fu["Priority"]==followup_priority]
        if not fu.empty:
            fu=fu.assign(_priority_order=pd.Categorical(fu["Priority"],categories=["High","Normal","Low"],ordered=True)).sort_values(["_priority_order","Created Time"])
            if action_right.button("Review next task",type="primary",key="review_next_followup"):
                st.session_state.followup_panel=fu.iloc[0]["Follow-up ID"]; st.rerun()
        if fu.empty:
            message_panel("success","All follow-up work is complete.",["There is nothing waiting for review."])
        else:
            st.caption("Review a task directly from its row.")
            for _,item_row in fu.iterrows():
                row_fid=item_row["Follow-up ID"]
                with app_card():
                    c1,c2,c3,action=st.columns([1.1,1.25,1.65,0.62],vertical_alignment="center")
                    c1.markdown(f"**{item_row['Trap ID']}**"); c1.caption(site_name(data,item_row["Site ID"]))
                    c2.write(item_row["Follow-up Type"]); c2.caption(item_row["Priority"])
                    c3.write(item_row["Reason"] or "—"); c3.caption(f"Created {human_dt(item_row['Created Time'])}")
                    if action.button("Review",key=f"followup_review_{row_fid}",use_container_width=True):
                        st.session_state.followup_panel=row_fid; st.rerun()
    else:
        matches=data["Followups"][data["Followups"]["Follow-up ID"]==selected_followup_id]
        if matches.empty:
            st.warning("This task no longer exists.")
            if st.button("Back to task list"):
                st.session_state.pop("followup_panel",None); st.rerun()
        else:
            item=matches.iloc[0]; fid=item["Follow-up ID"]; tr=trap_row(data,item["Trap ID"])
            if st.button("← Back to task list", key="back_followup_list"):
                st.session_state.pop("followup_panel",None); st.rerun()
            header(item["Follow-up Type"], f"{item['Trap ID']} · {site_name(data,item['Site ID'])}")

            linked_windows=data["Windows"][data["Windows"]["Window ID"]==item["Window ID"]]
            linked_window=linked_windows.iloc[0] if not linked_windows.empty else None
            window_start=parse_dt(linked_window["Start Time"]) if linked_window is not None else None
            window_end=parse_dt(linked_window["End Time"]) if linked_window is not None else None

            context_rows=[("Trap",item["Trap ID"]),("Site",site_name(data,item["Site ID"])),("Build",tr["Build Version"]),("Bag ID",item["Bag ID"]),("Reason",item["Reason"] or "Not recorded")]
            if window_start and window_end:
                context_rows.append(("Evidence period",f"{human_dt(window_start)} to {human_dt(window_end)}"))
            workflow_context(context_rows)
            if window_start and window_end:
                st.caption("Record when events occurred in the footage, not when you reviewed it.")
            min_evidence_date=window_start.date() if window_start else None
            max_evidence_date=window_end.date() if window_end else None

            st.markdown("### Complete this review")
            if item["Follow-up Type"]=="Camera review":
                is_kill_review=bool(str(item.get("Bag ID", "")).strip()) or (linked_window is not None and linked_window.get("Finding At Close", "")=="Dead animal found")
                prefix=f"cam_{fid}"
                evidence_usable=st.selectbox("Camera evidence usable",["Select…","Yes","No"],index=0,key=f"{prefix}_usable")
                target="Unclear"; interaction_level="Unclear"; strike_area="Unclear"; first_d=first_t=None
                activated="Unclear"; trigger_d=trigger_t=None; kill_d=kill_t=None
                assessment="Not applicable"

                if evidence_usable=="No":
                    st.info("No event timings are required. Add the evidence link or notes explaining the gap.")
                elif evidence_usable=="Yes":
                    if is_kill_review:
                        target="Yes"
                        st.write("**Target interaction:** Confirmed by this kill review")
                    else:
                        target=st.selectbox("Target animal interaction visible",["Select…","Yes","No","Unclear"],index=0,key=f"{prefix}_target")
                    if target=="Yes":
                        interaction_level=st.selectbox("Interaction level",["Select…","Single interaction","Repeated interaction","Heavy / repeated interaction"],index=0,key=f"{prefix}_level")
                        first_d=st.date_input("First target interaction date",value=None,min_value=min_evidence_date,max_value=max_evidence_date,key=f"{prefix}_first_d")
                        first_t=st.time_input("First target interaction time",value=None,key=f"{prefix}_first_t")
                        if is_kill_review:
                            strike_area="Yes"
                        else:
                            strike_area=st.selectbox("Entered the strike area",["Select…","Yes","No","Unclear"],index=0,key=f"{prefix}_strike")
                    elif target=="No":
                        interaction_level="Not applicable"; strike_area="Not applicable"
                    elif target=="Unclear":
                        interaction_level="Unclear"; strike_area="Unclear"

                    if is_kill_review:
                        st.caption("Activation and kill are implied by this confirmed-kill task.")
                        activated="Yes"
                        kill_d=st.date_input("Kill date",value=None,min_value=min_evidence_date,max_value=max_evidence_date,key=f"{prefix}_kill_d")
                        kill_t=st.time_input("Kill time",value=None,key=f"{prefix}_kill_t")
                        assessment=st.selectbox("Video humane-kill indicator",["Select…","Humane","Not humane","Unclear","No usable video"],index=0,key=f"{prefix}_assessment")
                    elif target=="Yes":
                        if strike_area=="Yes":
                            activated=st.selectbox("Trap activated",["Select…","Yes","No","Unclear"],index=0,key=f"{prefix}_activated")
                            if activated=="Yes":
                                trigger_d=st.date_input("First activation date",value=None,min_value=min_evidence_date,max_value=max_evidence_date,key=f"{prefix}_trigger_d")
                                trigger_t=st.time_input("First activation time",value=None,key=f"{prefix}_trigger_t")
                        elif strike_area=="No":
                            activated="No"
                            st.caption("Activation is not applicable because meaningful entry did not occur.")
                        elif strike_area=="Unclear":
                            activated="Unclear"
                    else:
                        activated="No" if target=="No" else "Unclear"

                link=st.text_input("Video link",key=f"{prefix}_link")
                notes=st.text_area("Notes",key=f"{prefix}_notes")

                saving_update("Attraction, interaction-to-kill speed, video assessment and the linked test-window review status." if is_kill_review else "Attraction, conversion, missed-kill classification and the linked test-window review status.")
                submit=st.button("Save camera review",type="primary",key=f"{prefix}_save")
                if submit:
                    errors=[]
                    if evidence_usable=="Select…": errors.append("Select whether the camera evidence is usable.")
                    if evidence_usable=="Yes" and not is_kill_review and target=="Select…": errors.append("Select whether target interaction is visible.")
                    if target=="Yes" and interaction_level=="Select…": errors.append("Select an interaction level.")
                    if not is_kill_review and target=="Yes" and strike_area=="Select…": errors.append("Select whether the animal entered the strike area.")
                    if target=="Yes" and (first_d is None or first_t is None): errors.append("Enter the first target interaction date and time.")
                    if is_kill_review and evidence_usable=="Yes":
                        if kill_d is None or kill_t is None: errors.append("Enter the kill date and time.")
                        if assessment=="Select…": errors.append("Select the video humane-kill indicator.")
                    if not is_kill_review and evidence_usable=="Yes" and target=="Yes" and strike_area=="Yes":
                        if activated=="Select…": errors.append("Select whether the trap activated.")
                        if activated=="Yes" and (trigger_d is None or trigger_t is None): errors.append("Enter the first activation date and time.")
                    if not is_kill_review and strike_area=="No" and activated=="Yes": errors.append("A trap cannot activate when meaningful entry did not occur.")
                    if not is_kill_review and target=="No" and strike_area not in ["Not applicable","Unclear"]: errors.append("Entry cannot be recorded when no target interaction occurred.")

                    first_dt=datetime.combine(first_d,first_t).replace(microsecond=0) if first_d is not None and first_t is not None else None
                    trigger_dt=datetime.combine(trigger_d,trigger_t).replace(microsecond=0) if trigger_d is not None and trigger_t is not None else None
                    kill_dt=datetime.combine(kill_d,kill_t).replace(microsecond=0) if kill_d is not None and kill_t is not None else None
                    idxs=data["Windows"].index[data["Windows"]["Window ID"]==item["Window ID"]].tolist()
                    if not idxs: errors.append("The linked test window cannot be found.")
                    else:
                        idx=idxs[0]; start_dt=parse_dt(data["Windows"].at[idx,"Start Time"]); end_dt=parse_dt(data["Windows"].at[idx,"End Time"])
                        for label,val in [("First interaction",first_dt),("Activation",trigger_dt),("Kill",kill_dt)]:
                            if val and start_dt and val<start_dt: errors.append(f"{label} time cannot be before the window started.")
                            if val and end_dt and val>end_dt: errors.append(f"{label} time cannot be after the field check closed the window.")
                        if first_dt and trigger_dt and trigger_dt<first_dt: errors.append("Activation time cannot be before first interaction.")
                        if first_dt and kill_dt and kill_dt<first_dt: errors.append("Kill time cannot be before first interaction.")
                    if errors:
                        st.error("Please correct the camera review:\n\n" + "\n".join(f"- {err}" for err in errors))
                    else:
                        if evidence_usable=="No":
                            target="Unclear"; interaction_level="Unclear"; strike_area="Unclear"; activated="Unclear"
                            assessment="No usable video" if is_kill_review else "Not applicable"
                        outcome=classify_camera_outcome(is_kill_review,evidence_usable,target,strike_area,activated,assessment)
                        idx=idxs[0]
                        kill_confirmed="Yes" if is_kill_review else "No"
                        activation_evidence="Inferred from kill" if is_kill_review else ("Observed" if activated=="Yes" and trigger_dt else "Not observed")
                        values={"Evidence Usable":evidence_usable,"Target Present":target,"Interaction Level":interaction_level,"Entered Strike Area":strike_area,"Trap Activated":activated,"Activation Evidence":activation_evidence,"Kill Confirmed":kill_confirmed,"Outcome":outcome,"First Interaction Time":dtstr(first_dt) if first_dt else "","Trigger Time":dtstr(trigger_dt) if trigger_dt else "","Kill Time":dtstr(kill_dt) if kill_dt else "","Video Assessment":assessment,"Video Link":link}
                        for k,v in values.items(): data["Windows"].at[idx,k]=v
                        recalculate_window(data,idx)
                        fidx=data["Followups"].index[data["Followups"]["Follow-up ID"]==fid][0]
                        data["Followups"].at[fidx,"Status"]="Complete"; data["Followups"].at[fidx,"Completed Time"]=dtstr(); data["Followups"].at[fidx,"Notes"]=notes
                        refresh_review_status(data,item["Window ID"]); save_data(data)
                        speed_line=f"Interaction to kill: {human_duration(minutes=data['Windows'].at[idx,'Interaction To Kill Min'])}." if is_kill_review and first_dt else "No interaction-to-kill time recorded."
                        set_flash("success","Camera review saved",[f"{item['Trap ID']} was updated.",speed_line,"Next: review the next open task."])
                        st.session_state.pop("followup_panel",None); st.rerun()

            elif item["Follow-up Type"]=="Necropsy review":
                prefix=f"nec_{fid}"
                status=st.selectbox("Necropsy status",["Select…","Complete","Not completed","Unable to assess"],index=0,key=f"{prefix}_status")
                assessment=st.selectbox("Necropsy assessment",["Select…","Supports humane kill","Does not support humane kill","Unclear","Not assessable"],index=0,key=f"{prefix}_assessment")
                weight_range=st.selectbox("Animal weight range",["Select…"]+ANIMAL_WEIGHT_RANGES,index=0,key=f"{prefix}_weight")
                final=st.selectbox("Final humane-kill result",["Select…","Yes","No","Unclear","Not assessable"],index=0,key=f"{prefix}_final")
                measurements=st.text_area("Measurements / findings",height=120,key=f"{prefix}_measurements")
                evidence=st.text_input("Evidence link",key=f"{prefix}_evidence")
                notes=st.text_area("Notes",key=f"{prefix}_notes")
                saving_update("The linked kill result, humane-kill KPI and test-window review status.")
                submit=st.button("Save necropsy review",type="primary",key=f"{prefix}_save")
                if submit:
                    errors=[]
                    if "Select…" in [status,assessment,weight_range,final]: errors.append("Complete all required necropsy fields.")
                    if status=="Complete" and assessment=="Not assessable": errors.append("A completed necropsy cannot be marked Not assessable.")
                    if assessment=="Supports humane kill" and final!="Yes": errors.append("A supportive necropsy must have a final humane-kill result of Yes.")
                    if assessment=="Does not support humane kill" and final!="No": errors.append("A non-supportive necropsy must have a final humane-kill result of No.")
                    if status in ["Not completed","Unable to assess"] and final in ["Yes","No"]: errors.append("Do not record a definite final result when the necropsy was not completed or assessable.")
                    idxs=data["Windows"].index[data["Windows"]["Window ID"]==item["Window ID"]].tolist()
                    if not idxs: errors.append("The linked test window cannot be found.")
                    if errors:
                        st.error("Please correct the necropsy review:\n\n" + "\n".join(f"- {err}" for err in errors))
                    else:
                        idx=idxs[0]
                        for k,v in {"Necropsy Status":status,"Necropsy Assessment":assessment,"Animal Weight Range":weight_range,"Necropsy Data Link":evidence,"Necropsy Measurements":measurements,"Final Humane Kill":final}.items(): data["Windows"].at[idx,k]=v
                        fidx=data["Followups"].index[data["Followups"]["Follow-up ID"]==fid][0]
                        data["Followups"].at[fidx,"Status"]="Complete"; data["Followups"].at[fidx,"Completed Time"]=dtstr(); data["Followups"].at[fidx,"Notes"]=notes
                        refresh_review_status(data,item["Window ID"]); save_data(data)
                        set_flash("success","Necropsy review saved",[f"Final humane-kill result: {final}.","The linked kill result and Performance metrics were updated.","Next: review the next open task."])
                        st.session_state.pop("followup_panel",None); st.rerun()
            else:
                prefix=f"issue_{fid}"
                resolution=st.selectbox("Camera outcome",["Select…","Fixed and now working","Adjusted and now covering trap","Replaced","Could not fix"],index=0,key=f"{prefix}_resolution")
                current_ready=st.selectbox("Camera now ready and covering the trap",["Select…","Yes","No","Could not assess"],index=0,key=f"{prefix}_ready")
                evidence_gap=st.selectbox("Past test-window evidence",["Select…","Still usable","Partly usable","Not usable","Could not assess"],index=0,key=f"{prefix}_gap")
                notes=st.text_area("Resolution notes",key=f"{prefix}_notes")
                saving_update("The task status, current camera readiness and the linked test-window evidence status.")
                if st.button("Save camera resolution",type="primary",key=f"{prefix}_save"):
                    errors=[]
                    if "Select…" in [resolution,current_ready,evidence_gap]: errors.append("Complete all camera-resolution fields.")
                    if resolution=="Could not fix" and current_ready=="Yes": errors.append("A camera that could not be fixed cannot be marked ready.")
                    if not notes.strip(): errors.append("Add a short resolution note.")
                    if errors:
                        st.error("Please correct the camera resolution:\n\n" + "\n".join(f"- {e}" for e in errors))
                    else:
                        fidx=data["Followups"].index[data["Followups"]["Follow-up ID"]==fid][0]
                        summary=f"{resolution}. Camera ready: {current_ready}. Past evidence: {evidence_gap}. {notes.strip()}"
                        data["Followups"].at[fidx,"Status"]="Complete"; data["Followups"].at[fidx,"Completed Time"]=dtstr(); data["Followups"].at[fidx,"Notes"]=summary
                        idxs=data["Windows"].index[data["Windows"]["Window ID"]==item["Window ID"]].tolist()
                        if idxs and evidence_gap in ["Not usable","Could not assess"]:
                            data["Windows"].at[idxs[0],"Evidence Usable"]="No"
                            recalculate_window(data,idxs[0])
                        refresh_review_status(data,item["Window ID"]); save_data(data)
                        set_flash("success","Camera resolution saved",[f"Current camera readiness: {current_ready}.",f"Past evidence: {evidence_gap}.","Next: review the next open task."])
                        st.session_state.pop("followup_panel",None); st.rerun()

elif page == "windows":
    if st.button("← Back to Data Management"):
        go("data_management")
    header("Trial periods", "Review active and completed trial periods.")
    controls_left, action_right = st.columns([4, 1], vertical_alignment="bottom")
    with controls_left:
        status_col, site_col = st.columns(2)
        visible_status = status_col.selectbox("Show windows", ["Closed", "Active", "All"], key="window_status_filter")
        window_site = site_col.selectbox("Site", ["All sites"] + data["Sites"]["Site ID"].tolist(), format_func=lambda x: x if x == "All sites" else site_name(data, x), key="window_site_filter")
    view=data["Windows"].copy()
    status_map = {"Closed": "Closed", "Active": "Open"}
    if visible_status in status_map:
        view=view[view["Status"]==status_map[visible_status]]
    if window_site != "All sites": view=view[view["Site ID"]==window_site]
    export_windows = view.to_csv(index=False).encode("utf-8")
    action_right.download_button("Export filtered", export_windows, file_name="test_windows_filtered.csv", mime="text/csv", key="export_filtered_windows")

    wid=st.session_state.get("window_panel")
    if wid:
        table, panel = st.columns([1.65,1], gap="large")
    else:
        table, panel = st.container(), None

    with table:
        if view.empty:
            helper("No test windows match this filter.")
        else:
            if visible_status == "Active":
                st.caption("Active windows are current field deployments. They are not results and do not require evidence review yet.")
            else:
                st.caption("Review a completed window directly from its row.")
            for _, wr_row in view.sort_values("Start Time", ascending=False).iterrows():
                row_wid = wr_row["Window ID"]
                with app_card():
                    c1, c2, c3, c4, action = st.columns([1.05, 1.1, 1.15, 1.1, 0.9], vertical_alignment="center")
                    c1.markdown(f"**{row_wid}**")
                    c1.caption(wr_row["Trap ID"])
                    c2.write(wr_row["Build Version"] or "—")
                    c2.caption(site_name(data, wr_row["Site ID"]))
                    c3.write(human_dt(wr_row["Start Time"]))
                    c3.caption("Started")
                    display_outcome = wr_row["Outcome"] if wr_row["Status"] == "Closed" else "Active"
                    c4.write(display_outcome or "—")
                    c4.caption(wr_row["Review Status"] if wr_row["Status"] == "Closed" else "Current deployment")
                    if action.button("Review", key=f"window_review_{row_wid}", use_container_width=True):
                        st.session_state.window_panel = row_wid
                        st.rerun()
    if panel is not None:
        with panel:
            wr=data["Windows"][data["Windows"]["Window ID"]==wid]
            if wr.empty:
                st.session_state.pop("window_panel",None)
                st.rerun()
            else:
                wr=wr.iloc[0]; st.subheader(wid); st.caption(f"{wr['Trap ID']} · {wr['Build Version']}")
                for label,col in [("Status","Status"),("Started","Start Time"),("Closed","End Time"),("Physical finding","Finding At Close"),("Outcome","Outcome"),("Target present","Target Present"),("Video assessment","Video Assessment"),("Necropsy assessment","Necropsy Assessment"),("Animal weight range","Animal Weight Range"),("Final humane kill","Final Humane Kill"),("Review status","Review Status")]:
                    value = human_dt(wr[col]) if col in ["Start Time", "End Time"] else (wr[col] or "—")
                    if col == "Status" and value == "Open": value = "Active"
                    st.write(f"**{label}:** {value}")
                if wr["Status"] == "Open":
                    helper("This window is still active. Evidence and final assessment are added only after the next field check closes it.")
                if st.button("Close panel", key="close_window_panel"): st.session_state.pop("window_panel",None); st.rerun()

elif page == "results":
    header("Trial performance", "See whether kills are humane and happen within the agreed time-to-kill target across the trial.")
    with app_card():
        product_col,build_col,site_col,export_col=st.columns([1,1.65,1,0.8],vertical_alignment="bottom")
        product=product_col.selectbox("Trap type",sorted(data["Builds"]["Product"].unique()))
        builds=data["Builds"][data["Builds"]["Product"]==product]
        current=builds[builds["Build Status"]=="Current"]["Build Version"].tolist()
        selected=build_col.selectbox("Build to assess",["Latest active build"]+builds["Build Version"].tolist()+["Compare builds","All builds — use with care"])
        site=site_col.selectbox("Site",["All sites"]+data["Sites"]["Site ID"].tolist(),format_func=lambda x:x if x=="All sites" else site_name(data,x))

    windows=data["Windows"][(data["Windows"]["Product"]==product)&(data["Windows"]["Status"]=="Closed")].copy()
    windows=windows[windows["End Time"].astype(str).str.strip()!=""]
    if selected=="Latest active build":
        windows=windows[windows["Build Version"].isin(current)]; context_label=f"Current build: {', '.join(current) if current else 'not configured'}"
    elif selected not in ["Compare builds","All builds — use with care"]:
        windows=windows[windows["Build Version"]==selected]; context_label=f"Build: {selected}"
    elif selected=="Compare builds": context_label="Comparing builds"
    else: context_label="All builds pooled"
    if site!="All sites": windows=windows[windows["Site ID"]==site]; context_label+=f" · {site_name(data,site)}"
    export_col.download_button("Export",windows.to_csv(index=False).encode("utf-8"),file_name="DEMO_results_filtered.csv" if is_demo_data else "results_filtered.csv",mime="text/csv",key="export_filtered_results",use_container_width=True)
    st.caption(context_label)
    if selected=="All builds — use with care": st.warning("These results combine different builds. Use them for exploration, not a single performance conclusion.")

    def median_numeric(df,col):
        vals=pd.to_numeric(df[col],errors="coerce").dropna()
        return vals.median() if not vals.empty else None

    # Explicit result populations keep whole-trial kill evidence separate from camera-sampled evidence.
    physical_kills=physical_kill_population(windows)
    confirmed_kills=physical_kills.copy()  # retained name for the breakdown and attention views
    humane=physical_kills[physical_kills["Final Humane Kill"]=="Yes"]
    non_humane=physical_kills[physical_kills["Final Humane Kill"]=="No"]
    final_pending=physical_kills[~physical_kills["Final Humane Kill"].isin(["Yes","No"])]
    assessed_kills=len(humane)+len(non_humane)
    humane_rate=len(humane)/assessed_kills*100 if assessed_kills else None

    # Time-to-kill only uses physical kills with usable camera evidence and valid footage timestamps.
    confirmed_kills["Interaction To Kill Numeric"]=pd.to_numeric(confirmed_kills["Interaction To Kill Min"],errors="coerce")
    timed_kills=confirmed_kills[(confirmed_kills["Evidence Usable"]=="Yes") & confirmed_kills["Interaction To Kill Numeric"].notna()].copy()
    within_target=timed_kills[timed_kills["Interaction To Kill Numeric"] < 24*60]
    missed_target=timed_kills[timed_kills["Interaction To Kill Numeric"] >= 24*60]
    timing_pending=physical_kills[~physical_kills["Window ID"].isin(timed_kills["Window ID"])]
    target_rate=len(within_target)/len(timed_kills)*100 if len(timed_kills) else None
    interaction_to_kill=timed_kills["Interaction To Kill Numeric"].median() if len(timed_kills) else None

    kill_evidence_complete=physical_kills[physical_kills["Final Humane Kill"].isin(["Yes","No"])]
    camera_windows=windows[windows["Camera Assigned"]=="Yes"].copy()
    camera_reviews_complete=camera_windows[camera_windows["Review Status"]=="Complete"]
    camera_reviews_open=camera_windows[camera_windows["Review Status"]=="Open"]
    unusable=camera_windows[camera_windows["Evidence Usable"]=="No"]

    st.subheader("Performance at a glance")
    outcome_card,time_card,evidence_card=st.columns(3)
    with outcome_card:
        with app_card():
            st.markdown("#### Kill outcome")
            st.metric("Good kills",len(humane))
            st.caption(f"Bad kills: {len(non_humane)}")
            st.write(f"**{humane_rate:.1f}% humane**" if humane_rate is not None else "**No completed humane assessments**")
            if len(final_pending): st.caption(f"{len(final_pending)} kill{'s' if len(final_pending)!=1 else ''} awaiting final assessment")
    with time_card:
        with app_card():
            st.markdown("#### Time to kill")
            st.metric("Met <24 hr target",f"{len(within_target)} of {len(timed_kills)}" if len(timed_kills) else "—")
            st.caption(f"Missed target: {len(missed_target)}")
            st.write(f"**Median: {human_duration(minutes=interaction_to_kill)}**" if interaction_to_kill is not None else "**No usable timing yet**")
            if len(timing_pending): st.caption(f"{len(timing_pending)} kill{'s' if len(timing_pending)!=1 else ''} without usable timing")
    with evidence_card:
        with app_card():
            st.markdown("#### Evidence")
            st.metric("Kill assessments complete",f"{len(kill_evidence_complete)} of {len(physical_kills)}")
            st.caption(f"Camera reviews complete: {len(camera_reviews_complete)} of {len(camera_windows)}")
            st.write(f"**Open camera reviews: {len(camera_reviews_open)} · Unusable footage: {len(unusable)}**")
            if not len(windows): st.caption("No closed windows in this selection")

    # Only surface exceptions that could change the decision.
    attention=confirmed_kills[
        (confirmed_kills["Final Humane Kill"]=="No") |
        (confirmed_kills["Interaction To Kill Numeric"] >= 24*60) |
        (confirmed_kills["Final Humane Kill"].isin(["","Pending","Unclear","Not assessable"])) |
        ((confirmed_kills["Camera Assigned"]=="Yes") & confirmed_kills["Interaction To Kill Numeric"].isna())
    ].copy()

    st.subheader("Camera conversion funnel")
    camera_traps=data["Traps"][(data["Traps"]["Product"]==product) & (data["Traps"]["Camera ID"].astype(str).str.strip()!="")]
    if site!="All sites": camera_traps=camera_traps[camera_traps["Site ID"]==site]
    camera_windows=windows[windows["Camera Assigned"]=="Yes"].copy()
    reviewed_camera=camera_windows[(camera_windows["Review Status"]=="Complete") & (camera_windows["Evidence Usable"]=="Yes")]
    interacted=reviewed_camera[reviewed_camera["Target Present"]=="Yes"]
    entered=interacted[interacted["Entered Strike Area"]=="Yes"]
    activated=entered[entered["Trap Activated"]=="Yes"]
    killed=activated[activated["Kill Confirmed"]=="Yes"]
    humane_funnel=killed[killed["Final Humane Kill"]=="Yes"]
    total_product_traps=data["Traps"][(data["Traps"]["Product"]==product) & (data["Traps"]["Status"]=="Active")]
    if site!="All sites": total_product_traps=total_product_traps[total_product_traps["Site ID"]==site]
    st.caption(f"Camera-sampled evidence · {len(camera_traps)} of {len(total_product_traps)} active traps have cameras · {len(reviewed_camera)} of {len(camera_windows)} closed camera windows reviewed with usable footage")
    stages=[("Rat interacted",len(interacted)),("Meaningful entry",len(entered)),("Trap activated",len(activated)),("Rat killed",len(killed)),("Humane kill",len(humane_funnel))]
    base=max(1,len(interacted))
    for i,(label,count) in enumerate(stages):
        prior=stages[i-1][1] if i else None
        conversion=(count/prior*100) if prior else None
        c1,c2=st.columns([1.2,3.8],vertical_alignment="center")
        c1.markdown(f"**{label}**  \n{count}" + (f" · {conversion:.0f}% from previous" if conversion is not None else ""))
        c2.progress(min(1.0,count/base))
    if len(interacted):
        losses=[("did not make meaningful entry",len(interacted)-len(entered)),("entered but did not activate",len(entered)-len(activated)),("activated but were not killed",len(activated)-len(killed)),("were killed but not confirmed humane",len(killed)-len(humane_funnel))]
        loss_label,loss_count=max(losses,key=lambda x:x[1])
        if loss_count>0: st.warning(f"Main loss: {loss_count} reviewed camera window{'s' if loss_count!=1 else ''} with rat interaction {loss_label}.")
    else:
        helper("No reviewed camera windows with target interaction are available for this selection.")

    st.subheader("What is driving the result?")
    st.caption("Use one breakdown at a time to see where bad kills or slow kills are clustering.")
    default_breakdown="Build" if selected=="Compare builds" else "Rodent weight"
    breakdown_options=["Rodent weight","Rat type","Build","Site","Trap"]
    breakdown=st.selectbox("Break down performance by",breakdown_options,index=breakdown_options.index(default_breakdown))

    group_map={
        "Rodent weight":"Animal Weight Range",
        "Rat type":"Rat Type",
        "Build":"Build Version",
        "Site":"Site ID",
        "Trap":"Trap ID",
    }
    group_col=group_map[breakdown]
    breakdown_source=confirmed_kills.copy()
    breakdown_source[group_col]=breakdown_source[group_col].fillna("").replace("","Unknown")

    if breakdown_source.empty:
        helper("No completed kills are available for this selection.")
    else:
        rows=[]
        for group_value,gp in breakdown_source.groupby(group_col,dropna=False):
            good=len(gp[gp["Final Humane Kill"]=="Yes"])
            bad=len(gp[gp["Final Humane Kill"]=="No"])
            assessed=good+bad
            gp_timed=gp[gp["Interaction To Kill Numeric"].notna()]
            met=len(gp_timed[gp_timed["Interaction To Kill Numeric"] < 24*60])
            missed=len(gp_timed[gp_timed["Interaction To Kill Numeric"] >= 24*60])
            rows.append({
                breakdown: site_name(data,group_value) if breakdown=="Site" and group_value!="Unknown" else group_value,
                "Kills":len(gp),
                "Good":good,
                "Bad":bad,
                "Humane":f"{good/assessed*100:.0f}%" if assessed else "—",
                "Met <24 hr":met,
                "Missed <24 hr":missed,
                "Time target":f"{met/len(gp_timed)*100:.0f}%" if len(gp_timed) else "—",
                "Median interaction → kill":human_duration(minutes=gp_timed["Interaction To Kill Numeric"].median()) if len(gp_timed) else "—",
            })
        breakdown_df=pd.DataFrame(rows)
        if breakdown=="Rodent weight":
            order={band:i for i,band in enumerate(ANIMAL_WEIGHT_RANGES)}; order["Unknown"]=99
            breakdown_df["_order"]=breakdown_df[breakdown].map(order).fillna(99)
            breakdown_df=breakdown_df.sort_values(["_order",breakdown]).drop(columns=["_order"])
        else:
            breakdown_df=breakdown_df.sort_values(breakdown)
        st.dataframe(breakdown_df,use_container_width=True,hide_index=True)

    if not attention.empty:
        st.subheader("Results needing attention")
        bad_count=len(non_humane)
        slow_count=len(missed_target)
        missing_count=len(attention[
            (~attention["Final Humane Kill"].isin(["Yes","No"])) |
            ((attention["Camera Assigned"]=="Yes") & attention["Interaction To Kill Numeric"].isna())
        ])
        summary_parts=[]
        if bad_count: summary_parts.append(f"{bad_count} bad kill{'s' if bad_count!=1 else ''}")
        if slow_count: summary_parts.append(f"{slow_count} kill{'s' if slow_count!=1 else ''} missed the time target")
        if missing_count: summary_parts.append(f"{missing_count} incomplete result{'s' if missing_count!=1 else ''}")
        st.warning(" · ".join(summary_parts))
        with st.expander(f"Review {len(attention)} result{'s' if len(attention)!=1 else ''}"):
            attention_display=attention.copy()
            attention_display["Interaction → kill"]=attention_display["Interaction To Kill Numeric"].apply(lambda x: human_duration(minutes=x) if pd.notna(x) else "—")
            cols=["Window ID","Site ID","Trap ID","Build Version","Animal Weight Range","Rat Type","Final Humane Kill","Interaction → kill","Review Status"]
            st.dataframe(attention_display[cols],use_container_width=True,hide_index=True)
    elif len(confirmed_kills):
        st.success("No bad kills, missed time targets or incomplete kill results in this selection.")

    with st.expander("More detail"):
        camera_assessed=windows[(windows["Camera Assigned"]=="Yes") & (windows["Review Status"]=="Complete") & (windows["Evidence Usable"]=="Yes") & (windows["Target Present"].isin(["Yes","No"]))]
        interacted=camera_assessed[camera_assessed["Target Present"]=="Yes"]
        activated=interacted[interacted["Trap Activated"]=="Yes"]
        observed_activation=activated[activated["Activation Evidence"]=="Observed"]
        killed=interacted[interacted["Kill Confirmed"]=="Yes"]
        repeated_no_kill=interacted[(interacted["Interaction Level"].isin(["Repeated interaction","Heavy / repeated interaction"])) & (interacted["Kill Confirmed"]!="Yes")]

        attraction_rate=len(interacted)/len(camera_assessed)*100 if len(camera_assessed) else None
        activation_rate=len(activated)/len(interacted)*100 if len(interacted) else None
        conversion_rate=len(killed)/len(interacted)*100 if len(interacted) else None
        deployment_to_interaction=median_numeric(interacted,"Time To First Interaction Hr")
        interaction_to_activation=median_numeric(observed_activation,"Interaction To Trigger Min")

        st.markdown("#### Diagnostic measures")
        d1,d2,d3,d4=st.columns(4)
        d1.metric("Target interaction",f"{attraction_rate:.0f}%" if attraction_rate is not None else "—")
        d1.caption(f"{len(interacted)} of {len(camera_assessed)} assessed windows")
        d2.metric("Interaction → activation",f"{activation_rate:.0f}%" if activation_rate is not None else "—")
        d2.caption(f"{len(activated)} of {len(interacted)} interactions")
        d3.metric("Interaction → kill",f"{conversion_rate:.0f}%" if conversion_rate is not None else "—")
        d3.caption(f"{len(killed)} of {len(interacted)} interactions")
        d4.metric("Repeated interaction, no kill",len(repeated_no_kill))

        st.markdown("#### Diagnostic timing")
        t1,t2=st.columns(2)
        t1.metric("Median deployment → interaction",human_duration(hours=deployment_to_interaction) if deployment_to_interaction is not None else "—")
        t2.metric("Median interaction → observed activation",human_duration(minutes=interaction_to_activation) if interaction_to_activation is not None else "—")
        t2.caption(f"Based on {len(observed_activation)} observed activations; inferred activations excluded")

        st.markdown("#### All closed result records")
        cols=["Window ID","Site ID","Trap ID","Build Version","Animal Weight Range","Rat Type","Evidence Usable","Target Present","Interaction Level","Trap Activated","Activation Evidence","Kill Confirmed","Outcome","Interaction To Kill Min","Final Humane Kill","Review Status"]
        st.dataframe(windows[cols],use_container_width=True,hide_index=True)

        st.markdown("#### Calculation definitions")
        st.write("**Physical kill:** a closed window where a dead animal was found, whether or not a camera was assigned.")
        st.write("**Good kill:** a physical kill with final humane-kill assessment Yes.")
        st.write("**Bad kill:** final humane-kill assessment is No.")
        st.write("**Met time target:** first confirmed target interaction to confirmed kill is strictly less than 24 hours.")
        st.write("**Humane rate:** good kills divided by good plus bad kills with a completed final assessment.")
        st.write("**Time-target rate:** physical kills under 24 hours divided by physical kills with usable camera footage and valid interaction-to-kill timing.")
        st.write("**Camera funnel:** completed, usable camera reviews only; it does not represent non-camera traps.")
        st.write("**Diagnostic conversion measures:** retained for investigation, but do not drive the top-line result.")


elif page == "setup":
    header("Trial setup", "Manage the sites, traps and build versions used in this trial.")
    section = st.radio("What do you need to manage?", ["Traps", "Trap sites", "Builds"], horizontal=True)
    helper("Select a record to edit or add a new one. Historical visit and result records are preserved.")

    if section == "Traps":
        mode = st.session_state.get("setup_mode")
        if mode in ["edit", "add"]:
            list_col, panel = st.columns([1.65, 1], gap="large")
        else:
            list_col, panel = st.container(), None
        with list_col:
            filter_col, action_col = st.columns([4, 1], vertical_alignment="bottom")
            site_filter = filter_col.selectbox("Show traps from", ["All sites"] + data["Sites"]["Site ID"].tolist(), format_func=lambda x: x if x=="All sites" else site_name(data,x), key="setup_trap_site")
            if action_col.button("Add trap", type="primary"):
                st.session_state.setup_trap=""; st.session_state.setup_mode="add"; st.rerun()
            view=data["Traps"].copy()
            if site_filter!="All sites": view=view[view["Site ID"]==site_filter]
            if view.empty:
                helper("No traps match this filter.")
            else:
                view = view.assign(_route_num=pd.to_numeric(view["Route Order"], errors="coerce"))
                for _, tr in view.sort_values(["Site ID", "_route_num"]).iterrows():
                    trap_id = tr["Trap ID"]
                    with app_card():
                        c1, c2, c3, c4, action = st.columns([1.05, 1.25, 1.0, 1.0, 0.7], vertical_alignment="center")
                        c1.markdown(f"**{trap_id}**")
                        c1.caption(tr["Product"])
                        c2.write(trap_location_label(tr))
                        c2.caption(site_name(data, tr["Site ID"]))
                        c3.write(tr["Build Version"] or "—")
                        c3.caption(f"Trap {tr['Route Order']}")
                        c4.write(tr["Camera ID"] or "No camera")
                        c4.caption(tr["Status"])
                        if action.button("Edit", key=f"setup_edit_trap_{trap_id}"):
                            st.session_state.setup_trap=trap_id; st.session_state.setup_mode="edit"; st.rerun()
        if panel is not None:
            with panel:
                existing = trap_row(data,st.session_state.setup_trap) if mode=="edit" else None
                setup_title, setup_close = st.columns([1, 0.13], vertical_alignment="top")
                with setup_title:
                    st.subheader("Edit trap" if mode=="edit" else "Add trap")
                with setup_close:
                    st.markdown('<span class="drawer-close-marker"></span>', unsafe_allow_html=True)
                    if st.button("×", key="close_trap_setup_panel_top", help="Close trap editor"):
                        st.session_state.pop("setup_mode", None)
                        st.session_state.pop("setup_trap", None)
                        st.rerun()
                with st.form("trap_setup_panel"):
                    trap_id=st.text_input("Trap ID",value=existing["Trap ID"] if existing is not None else "",disabled=mode=="edit")
                    product=st.selectbox("Trap type",sorted(data["Builds"]["Product"].unique()),index=(sorted(data["Builds"]["Product"].unique()).index(existing["Product"]) if existing is not None and existing["Product"] in sorted(data["Builds"]["Product"].unique()) else 0))
                    build_options=data["Builds"][data["Builds"]["Product"]==product]["Build Version"].tolist() or [""]
                    build=st.selectbox("Build",build_options,index=(build_options.index(existing["Build Version"]) if existing is not None and existing["Build Version"] in build_options else 0))
                    site_options=data["Sites"]["Site ID"].tolist(); site=st.selectbox("Site",site_options,index=(site_options.index(existing["Site ID"]) if existing is not None and existing["Site ID"] in site_options else 0),format_func=lambda x:site_name(data,x))
                    location=st.text_input("Location description", value=trap_location_label(existing) if existing is not None else "")
                    camera=st.text_input("Camera ID",value=existing["Camera ID"] if existing is not None else "")
                    order=st.number_input("Trap order",min_value=1,step=1,value=int(float(existing["Route Order"])) if existing is not None and str(existing["Route Order"]).strip() else 1)
                    deployment=parse_dt(existing["Deployment Start"]) if existing is not None else now()
                    dep_date=st.date_input("Deployment start date",value=deployment.date() if deployment else now().date())
                    dep_time=st.time_input("Deployment start time",value=deployment.time() if deployment else now().time())
                    image=st.text_input("Setup image link",value=existing["Setup Image Link"] if existing is not None else "")
                    status=st.selectbox("Status",["Active","Inactive"],index=0 if existing is None or existing["Status"]=="Active" else 1)
                    notes=st.text_area("Notes",value=existing["Notes"] if existing is not None else "")
                    save=st.form_submit_button("Save trap changes" if mode=="edit" else "Add trap",type="primary")
                if save:
                    if not trap_id.strip(): st.error("Trap ID is required.")
                    elif mode=="add" and trap_id in data["Traps"]["Trap ID"].tolist(): st.error("That Trap ID already exists.")
                    else:
                        row=[trap_id,product,build,site,str(order),location,camera,dtstr(datetime.combine(dep_date,dep_time)),image,status,notes]
                        if mode=="edit":
                            idx=data["Traps"].index[data["Traps"]["Trap ID"]==trap_id][0]
                            old_build=data["Traps"].at[idx,"Build Version"]
                            if old_build!=build and open_window(data,trap_id) is not None:
                                st.error("Close the active test window before changing this trap's build.")
                            else: data["Traps"].loc[idx,SHEETS["Traps"]]=row; save_data(data); set_flash("success", f"{trap_id} updated.", ["Trap setup changes were saved."]); st.session_state.pop("setup_mode",None); st.session_state.pop("setup_trap",None); st.rerun()
                        else:
                            data["Traps"]=pd.concat([data["Traps"],pd.DataFrame([row],columns=SHEETS["Traps"])],ignore_index=True); save_data(data); set_flash("success", f"{trap_id} added.", ["The trap is now available at its site."]); st.session_state.pop("setup_mode",None); st.rerun()
                if st.button("Cancel",key="cancel_trap_panel"): st.session_state.pop("setup_mode",None); st.session_state.pop("setup_trap",None); st.rerun()
    elif section == "Trap sites":
        mode = st.session_state.get("site_mode")
        if mode in ["edit", "add"]:
            list_col, panel = st.columns([1.65, 1], gap="large")
        else:
            list_col, panel = st.container(), None
        with list_col:
            spacer, action_col = st.columns([4, 1], vertical_alignment="bottom")
            if action_col.button("Add site", type="primary"):
                st.session_state.setup_site=""; st.session_state.site_mode="add"; st.rerun()
            for _, site_row in data["Sites"].sort_values("Site Name").iterrows():
                sid = site_row["Site ID"]
                trap_count = len(data["Traps"][(data["Traps"]["Site ID"] == sid) & (data["Traps"]["Status"] == "Active")])
                with app_card():
                    c1, c2, c3, action = st.columns([1.3, 1.0, 1.15, 0.7], vertical_alignment="center")
                    c1.markdown(f"**{site_row['Site Name']}**")
                    c1.caption(sid)
                    c2.write(f"{trap_count} active traps")
                    c2.caption(f"Every {site_row['Visit Interval Days']} days")
                    c3.write(site_row["Status"])
                    c3.caption("Mobile coverage confirmed" if site_row.get("Mobile Coverage Confirmed","")=="Yes" else "Mobile coverage not confirmed")
                    if action.button("Edit", key=f"setup_edit_site_{sid}"):
                        st.session_state.setup_site=sid; st.session_state.site_mode="edit"; st.rerun()
        if panel is not None:
            with panel:
                ex=data["Sites"][data["Sites"]["Site ID"]==st.session_state.get("setup_site","")].iloc[0] if mode=="edit" else None
                st.subheader("Edit site" if mode=="edit" else "Add site")
                with st.form("site_setup_panel"):
                    sid=st.text_input("Site ID",value=ex["Site ID"] if ex is not None else "",disabled=mode=="edit")
                    name=st.text_input("Site name",value=ex["Site Name"] if ex is not None else "")
                    interval=3
                    st.number_input("Visit interval days",min_value=3,max_value=3,step=1,value=3,disabled=True,help="The trial method is currently fixed at a 3-day check interval.")
                    coverage=st.selectbox("Mobile coverage confirmed",["Yes","No"],index=0 if ex is not None and ex.get("Mobile Coverage Confirmed","")=="Yes" else 1,help="Only activate sites with reliable mobile data coverage across the site.")
                    status=st.selectbox("Status",["Active","Inactive"],index=0 if ex is None or ex["Status"]=="Active" else 1)
                    notes=st.text_area("Notes",value=ex["Notes"] if ex is not None else "")
                    save=st.form_submit_button("Save site changes" if mode=="edit" else "Add site",type="primary")
                if save:
                    sid=normalise_site_code(sid)
                    code_error=validate_site_code(sid)
                    if code_error:
                        st.error(code_error); st.stop()
                    if not name.strip():
                        st.error("Site name is required."); st.stop()
                    if mode=="add" and sid in data["Sites"]["Site ID"].astype(str).str.upper().tolist():
                        st.error("That site code already exists."); st.stop()
                    if status=="Active" and coverage!="Yes":
                        st.error("Confirm reliable mobile coverage before activating this site."); st.stop()
                    row=[sid,name.strip(),str(interval),coverage,status,notes]
                    if mode=="edit":
                        idx=data["Sites"].index[data["Sites"]["Site ID"]==sid][0]
                        data["Sites"].loc[idx,SHEETS["Sites"]]=row
                    else:
                        data["Sites"]=pd.concat([data["Sites"],pd.DataFrame([row],columns=SHEETS["Sites"])],ignore_index=True)
                    save_data(data); set_flash("success", f"{name.strip()} saved.", ["Site settings were updated."]); st.session_state.pop("site_mode",None); st.rerun()

                if mode=="edit":
                    st.divider()
                    with st.expander("Rename site code"):
                        st.warning("This changes the site code across all linked records. Trap IDs, bag IDs and existing record IDs will not be renamed.")
                        st.caption(f"Current site code: {ex['Site ID']}")
                        affected_counts=site_code_link_counts(data, ex["Site ID"])
                        st.markdown("**This rename will update**")
                        preview_cols=st.columns(3)
                        preview_items=[
                            ("Traps",affected_counts.get("Traps",0)),
                            ("Visits",affected_counts.get("Visits",0)),
                            ("Test windows",affected_counts.get("Windows",0)),
                            ("Follow-up tasks",affected_counts.get("Followups",0)),
                            ("Photos",affected_counts.get("Photos",0)),
                        ]
                        for position,(label,count) in enumerate(preview_items):
                            preview_cols[position % 3].metric(label,count)

                        new_site_code=st.text_input(
                            "New site code",
                            value="",
                            placeholder="e.g. MGF",
                            key=f"rename_site_code_{ex['Site ID']}",
                        )
                        rename_reason=st.text_area(
                            "Reason for rename",
                            placeholder="Why is the site code changing?",
                            key=f"rename_site_reason_{ex['Site ID']}",
                        )
                        confirm_rename=st.checkbox(
                            "I understand this updates every linked Site ID reference and moves linked evidence files",
                            key=f"confirm_site_rename_{ex['Site ID']}",
                        )
                        if st.button("Rename site code", type="primary", key=f"rename_site_button_{ex['Site ID']}"):
                            if not rename_reason.strip():
                                st.error("Enter a reason for the rename.")
                            elif not confirm_rename:
                                st.error("Confirm that you understand the linked records and evidence files will be updated.")
                            else:
                                try:
                                    renamed_data, counts, moved_files=commit_site_code_rename(
                                        data, ex["Site ID"], new_site_code, rename_reason
                                    )
                                    new_code=normalise_site_code(new_site_code)
                                    if st.session_state.get("site_id")==ex["Site ID"]:
                                        st.session_state.site_id=new_code
                                    st.session_state.setup_site=new_code
                                    total_links=sum(count for name,count in counts.items() if name!="Sites")
                                    set_flash(
                                        "success",
                                        f"Site code changed from {ex['Site ID']} to {new_code}.",
                                        [
                                            f"{total_links} linked record{'s' if total_links != 1 else ''} updated.",
                                            f"{moved_files} evidence file{'s' if moved_files != 1 else ''} moved.",
                                            "Trap IDs, bag IDs and existing record IDs were left unchanged.",
                                            "A unique workbook backup and audit-log entry were created.",
                                        ],
                                    )
                                    st.rerun()
                                except Exception as exc:
                                    st.error(f"Site code was not changed: {exc}")

                if st.button("Cancel",key="cancel_site_panel"): st.session_state.pop("site_mode",None); st.rerun()
    else:
        mode = st.session_state.get("build_mode")
        if mode in ["edit", "add"]:
            list_col, panel = st.columns([1.65, 1], gap="large")
        else:
            list_col, panel = st.container(), None
        with list_col:
            spacer, action_col = st.columns([4, 1], vertical_alignment="bottom")
            if action_col.button("Add build", type="primary"):
                st.session_state.setup_build=""; st.session_state.build_mode="add"; st.rerun()
            for _, build_row in data["Builds"].sort_values(["Product", "First Active Date"], ascending=[True, False]).iterrows():
                version = build_row["Build Version"]
                active_traps = len(data["Traps"][(data["Traps"]["Build Version"] == version) & (data["Traps"]["Status"] == "Active")])
                with app_card():
                    c1, c2, c3, action = st.columns([1.15, 1.15, 1.3, 0.7], vertical_alignment="center")
                    c1.markdown(f"**{version}**")
                    c1.caption(build_row["Product"])
                    c2.write(build_row["Build Status"])
                    c2.caption(f"{active_traps} active traps")
                    c3.write((parse_dt(build_row["First Active Date"]).strftime("%d %b %Y") if parse_dt(build_row["First Active Date"]) else "—"))
                    c3.caption(build_row["Notes"] or "No notes")
                    if action.button("Edit", key=f"setup_edit_build_{version}"):
                        st.session_state.setup_build=version; st.session_state.build_mode="edit"; st.rerun()
        if panel is not None:
            with panel:
                ex=data["Builds"][data["Builds"]["Build Version"]==st.session_state.get("setup_build","")].iloc[0] if mode=="edit" else None
                st.subheader("Edit build" if mode=="edit" else "Add build")
                with st.form("build_setup_panel"):
                    product=st.selectbox("Trap type",["R1","M1"],index=0 if ex is None or ex["Product"]=="R1" else 1)
                    version=st.text_input("Build version",value=ex["Build Version"] if ex is not None else "",disabled=mode=="edit")
                    status=st.selectbox("Build status",["Current","Trial comparison","Superseded","Withdrawn"],index=(["Current","Trial comparison","Superseded","Withdrawn"].index(ex["Build Status"]) if ex is not None and ex["Build Status"] in ["Current","Trial comparison","Superseded","Withdrawn"] else 0))
                    first=parse_dt(ex["First Active Date"]) if ex is not None else now(); first_date=st.date_input("First active date",value=first.date() if first else now().date())
                    notes=st.text_area("Notes",value=ex["Notes"] if ex is not None else "")
                    save=st.form_submit_button("Save build changes" if mode=="edit" else "Add build",type="primary")
                if save:
                    row=[product,version,status,first_date.strftime("%Y-%m-%d"),notes]
                    if mode=="edit": idx=data["Builds"].index[data["Builds"]["Build Version"]==version][0]; data["Builds"].loc[idx,SHEETS["Builds"]]=row
                    else: data["Builds"]=pd.concat([data["Builds"],pd.DataFrame([row],columns=SHEETS["Builds"])],ignore_index=True)
                    save_data(data); set_flash("success", f"{version} saved.", ["Build settings were updated."]); st.session_state.pop("build_mode",None); st.rerun()
                if st.button("Cancel",key="cancel_build_panel"): st.session_state.pop("build_mode",None); st.rerun()
elif page == "data_management":
    header("Data & records", "Correct records, review trial periods and changes, or export the workbook.")
    corrections_tab, history_tab, audit_tab, export_tab = st.tabs(["Corrections", "Trial history", "Audit log", "Export and backup"])

    with corrections_tab:
        helper("Use corrections only for known data-entry mistakes. Every change requires a reason and is retained in the audit log.")
        st.markdown("#### What you are recording")
        st.write("The corrected value and why the original entry was wrong.")
        st.markdown("#### What the app will update")
        st.write("The linked record, any affected Performance figures, and a permanent audit-log entry.")
        record_type = st.selectbox("Record type", ["Camera evidence", "Necropsy evidence", "Field check"])
        search_text = st.text_input("Find by trap, window, bag or check ID").strip().lower()

        if record_type in ["Camera evidence", "Necropsy evidence"]:
            candidates = data["Windows"][data["Windows"]["Status"] == "Closed"].copy()
            if search_text:
                mask = candidates[["Window ID", "Trap ID", "Bag ID", "Site ID"]].astype(str).apply(lambda col: col.str.lower().str.contains(search_text, na=False)).any(axis=1)
                candidates = candidates[mask]
            options = candidates["Window ID"].tolist()
            selected_id = st.selectbox("Select closed test window", options, format_func=lambda wid: (lambda r: f"{r['Trap ID']} · {site_name(data, r['Site ID'])} · {human_dt(r['End Time'])} · {wid}")(candidates[candidates['Window ID']==wid].iloc[0]) if wid else wid) if options else None
            if selected_id:
                idx = data["Windows"].index[data["Windows"]["Window ID"] == selected_id][0]
                row = data["Windows"].loc[idx]
                st.caption(f"Evidence period: {human_dt(row['Start Time'])} – {human_dt(row['End Time'])}")
                if record_type == "Camera evidence":
                    editable = {
                        "Evidence Usable": ["Yes", "No", "Pending"],
                        "Target Present": ["Yes", "No", "Unclear", "Pending"],
                        "Interaction Level": ["Single interaction", "Repeated interaction", "Heavy / repeated interaction", "Not applicable", "Unclear", "Pending"],
                        "Entered Strike Area": ["Yes", "No", "Unclear", "Not applicable", "Pending"],
                        "Trap Activated": ["Yes", "No", "Unclear", "Pending"],
                        "Kill Confirmed": ["Yes", "No", "Unclear", "Pending"],
                        "Video Assessment": ["Humane", "Not humane", "Unclear", "No usable video", "Not applicable", "Pending"],
                    }
                    changed = {}
                    with st.form("correct_camera_evidence"):
                        for field, choices in editable.items():
                            current = str(row[field])
                            index = choices.index(current) if current in choices else 0
                            changed[field] = st.selectbox(field, choices, index=index, key=f"corr_{field}")
                        reason = st.text_area("Correction reason")
                        save_correction = st.form_submit_button("Save correction", type="primary")
                else:
                    editable = {
                        "Necropsy Status": ["Complete", "Not completed", "Unable to assess", "Not started"],
                        "Necropsy Assessment": ["Supports humane kill", "Does not support humane kill", "Unclear", "Not assessable", "Pending"],
                        "Animal Weight Range": ANIMAL_WEIGHT_RANGES + [""],
                        "Final Humane Kill": ["Yes", "No", "Unclear", "Not assessable", "Pending"],
                    }
                    changed = {}
                    with st.form("correct_necropsy_evidence"):
                        for field, choices in editable.items():
                            current = str(row[field])
                            index = choices.index(current) if current in choices else 0
                            changed[field] = st.selectbox(field, choices, index=index, key=f"corr_{field}")
                        reason = st.text_area("Correction reason")
                        save_correction = st.form_submit_button("Save correction", type="primary")
                if save_correction:
                    if not reason.strip():
                        st.error("Enter a correction reason before saving.")
                    else:
                        audit_rows = []
                        for field, new_value in changed.items():
                            old_value = str(data["Windows"].at[idx, field])
                            if str(new_value) != old_value:
                                data["Windows"].at[idx, field] = new_value
                                audit_rows.append([make_id("CHG"), dtstr(), record_type, selected_id, field, old_value, str(new_value), reason.strip()])
                        if audit_rows:
                            recalculate_window(data,idx)
                            refresh_review_status(data,selected_id)
                            data["Audit Log"] = pd.concat([data["Audit Log"], pd.DataFrame(audit_rows, columns=SHEETS["Audit Log"])], ignore_index=True)
                            save_data(data)
                            set_flash("success", "Correction saved.", [f"{len(audit_rows)} field change(s) were applied.", "The audit log retained the previous and corrected values.", "Next: make another correction or return to the relevant record."])
                            st.rerun()
                        else:
                            st.info("No values changed.")
        else:
            candidates = data["Checks"].copy()
            if search_text:
                mask = candidates[["Check ID", "Trap ID", "Bag ID", "Visit ID"]].astype(str).apply(lambda col: col.str.lower().str.contains(search_text, na=False)).any(axis=1)
                candidates = candidates[mask]
            options = candidates["Check ID"].tolist()
            selected_id = st.selectbox("Select field check", options, format_func=lambda cid: (lambda r: f"{r['Trap ID']} · {human_dt(r['Check Time'])} · {r['Finding']} · {cid}")(candidates[candidates['Check ID']==cid].iloc[0]) if cid else cid) if options else None
            if selected_id:
                idx = data["Checks"].index[data["Checks"]["Check ID"] == selected_id][0]
                row = data["Checks"].loc[idx]
                with st.form("correct_field_check"):
                    finding_choices = FINDINGS
                    finding = st.selectbox("Finding", finding_choices, index=finding_choices.index(row["Finding"]) if row["Finding"] in finding_choices else 0)
                    notes = st.text_area("Notes", value=row["Notes"])
                    reason = st.text_area("Correction reason")
                    save_correction = st.form_submit_button("Save correction", type="primary")
                if save_correction:
                    if not reason.strip():
                        st.error("Enter a correction reason before saving.")
                    else:
                        changed = {"Finding": finding, "Notes": notes}
                        audit_rows=[]
                        for field,new_value in changed.items():
                            old_value=str(data["Checks"].at[idx,field])
                            if str(new_value)!=old_value:
                                data["Checks"].at[idx,field]=new_value
                                audit_rows.append([make_id("CHG"),dtstr(),record_type,selected_id,field,old_value,str(new_value),reason.strip()])
                        if audit_rows:
                            data["Audit Log"] = pd.concat([data["Audit Log"], pd.DataFrame(audit_rows, columns=SHEETS["Audit Log"])], ignore_index=True)
                            save_data(data); set_flash("success","Correction saved.",[f"{len(audit_rows)} field change(s) were applied.","The audit log retained the previous and corrected values.","Next: make another correction or return to the relevant record."]); st.rerun()
                        else: st.info("No values changed.")

    with history_tab:
        helper("Trial history shows each period between a trap being set or relured and its next field check.")
        st.write("Use it to trace how a field finding, camera review and final performance result link together.")
        if st.button("Open trial history", type="primary", key="open_trial_history"):
            go("windows")

    with audit_tab:
        if data["Audit Log"].empty:
            st.info("No corrections have been recorded yet.")
        else:
            audit_view = data["Audit Log"].copy().iloc[::-1]
            st.dataframe(audit_view, use_container_width=True, hide_index=True)

    with export_tab:
        sheet = st.selectbox("Inspect data table", list(SHEETS), key="data_management_sheet")
        st.dataframe(data[sheet], use_container_width=True, hide_index=True)
        st.caption("Export is read-only. Opening this page does not change trial data.")
        with open(DATA_FILE, "rb") as f:
            st.download_button("Download complete Excel backup", f, file_name=DATA_FILE.name, type="primary")

st.sidebar.divider()
st.sidebar.caption("v8.6.67 · Message Contrast and Header Clearance Fix")
st.sidebar.caption(f"Environment: {DEPLOYMENT_ENVIRONMENT}")
st.sidebar.caption(f"Data folder: {DATA_ROOT}")
if st.sidebar.button("Sign out", key="sign_out"):
    st.session_state.clear()
    st.rerun()
if storage_is_potentially_ephemeral():
    st.sidebar.error("Storage may be temporary. Set R1M1_DATA_DIR to a persistent mounted folder before field use.")
else:
    st.sidebar.caption("Storage check: writable · atomic workbook saves · automatic backups")
