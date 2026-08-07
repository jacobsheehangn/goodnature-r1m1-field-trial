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

from photo_integrity import (
    PhotoPermanentError,
    PhotoTransientError,
    add_expected_photos,
    apply_final_copies,
    build_finalisation_plan,
    cleanup_stale_transactions,
    delete_transaction,
    deterministic_check_id,
    log_photo_event,
    mark_retry_started,
    record_failure,
    recover_bag_id,
    remove_photo as remove_pending_photo,
    rollback_final_copies,
    store_photo as store_pending_photo,
    verify_pending as verify_pending_photo_transaction,
)

APP_TITLE = "R1/M1 Field Trial — v8.7.6.7 Photo Integrity Corrections"
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
MAX_PHOTO_DIMENSION = 1800
PHOTO_COMPONENT_DIR = APP_DIR / "photo_component"
PHOTO_COMPONENT = components.declare_component("r1m1_photo_upload", path=str(PHOTO_COMPONENT_DIR))

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




AUTH_QUERY_KEY = "access"
AUTH_TOKEN_PURPOSE = "r1m1-staging-access-v1"


def expected_access_token() -> str:
    """Return a stable signed token derived from the configured shared password."""
    return hmac.new(
        APP_PASSWORD.encode("utf-8"),
        AUTH_TOKEN_PURPOSE.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def query_access_token() -> str:
    """Read the access token from the current browser URL."""
    value = st.query_params.get(AUTH_QUERY_KEY, "")
    if isinstance(value, list):
        value = value[-1] if value else ""
    return str(value)


def access_token_is_valid() -> bool:
    if not APP_PASSWORD:
        return False
    supplied = query_access_token()
    return bool(supplied) and hmac.compare_digest(
        supplied,
        expected_access_token(),
    )


def require_authentication() -> None:
    """Require the shared pilot password before loading or displaying trial data."""
    if st.session_state.get("authenticated"):
        if APP_PASSWORD and not access_token_is_valid():
            st.query_params[AUTH_QUERY_KEY] = expected_access_token()
        return

    if not APP_PASSWORD:
        if ALLOW_NO_AUTH and DEPLOYMENT_ENVIRONMENT == "local":
            st.session_state.authenticated = True
            return
        st.error("App access is not configured.")
        st.caption("Set the R1M1_APP_PASSWORD environment variable, then restart the app.")
        st.stop()

    # A valid signed URL token restores access after browser refresh without storing
    # or exposing the shared password.
    if access_token_is_valid():
        st.session_state.authenticated = True
        st.query_params[AUTH_QUERY_KEY] = expected_access_token()
        return

    logo_path = APP_DIR / "goodnature_logo.png"
    st.markdown(
        '<span class="login-page-marker" aria-hidden="true"></span>',
        unsafe_allow_html=True,
    )
    if logo_path.exists():
        st.image(str(logo_path), width=220)
    st.markdown('<h1 class="login-title">R1/M1 field trial</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="login-intro">Enter the trial password to continue.</p>',
        unsafe_allow_html=True,
    )
    with st.form("login_form", clear_on_submit=False):
        supplied_password = st.text_input(
            "Password",
            type="password",
            autocomplete="current-password",
        )
        submitted = st.form_submit_button(
            "Sign in",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if hmac.compare_digest(supplied_password, APP_PASSWORD):
            st.session_state.authenticated = True
            st.session_state.failed_login_attempts = 0
            st.query_params[AUTH_QUERY_KEY] = expected_access_token()
            st.rerun()
        else:
            attempts = int(st.session_state.get("failed_login_attempts", 0)) + 1
            st.session_state.failed_login_attempts = attempts
            st.error("Incorrect password.")
            if attempts >= 5:
                st.caption(
                    "Several attempts have failed. Check the password with the trial lead."
                )

    st.markdown(
        '<p class="login-security">Trial data is restricted to authorised Goodnature users.</p>',
        unsafe_allow_html=True,
    )
    st.stop()



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



def trap_link_counts(data, trap_id):
    """Return linked-record counts used to protect trap history."""
    counts = {}
    for sheet in ["Checks", "Windows", "Followups", "Photos"]:
        frame = data[sheet]
        counts[sheet] = int((frame["Trap ID"].astype(str) == str(trap_id)).sum()) if "Trap ID" in frame.columns else 0
    return counts


def trap_can_be_deleted(data, trap_id):
    """Allow deletion only before any field activity or follow-up exists."""
    counts = trap_link_counts(data, trap_id)
    if counts["Checks"] or counts["Followups"] or counts["Photos"]:
        return False
    windows = data["Windows"][data["Windows"]["Trap ID"].astype(str) == str(trap_id)]
    if windows.empty:
        return True
    # A newly-created untouched open window may be removed with the trap.
    return (
        len(windows) == 1
        and str(windows.iloc[0]["Status"]) == "Open"
        and not str(windows.iloc[0]["End Time"]).strip()
        and not str(windows.iloc[0]["Finding At Close"]).strip()
    )


def delete_unused_trap(data, trap_id):
    if not trap_can_be_deleted(data, trap_id):
        raise ValueError("This trap has trial history and cannot be deleted. Set it to Inactive instead.")
    data["Windows"] = data["Windows"][data["Windows"]["Trap ID"].astype(str) != str(trap_id)].copy()
    data["Traps"] = data["Traps"][data["Traps"]["Trap ID"].astype(str) != str(trap_id)].copy()
    save_data(data)



def audit_change(data, record_type, record_id, field, previous, new, reason):
    data["Audit Log"] = pd.concat([
        data["Audit Log"],
        pd.DataFrame([[
            make_id("CHG"), dtstr(), record_type, record_id, field,
            str(previous), str(new), reason
        ]], columns=SHEETS["Audit Log"])
    ], ignore_index=True)


def repair_missing_window(data, trap_id, effective_time=None, reason="Missing test window repaired"):
    if open_window(data, trap_id) is not None:
        return str(open_window(data, trap_id)["Window ID"])
    tr = trap_row(data, trap_id)
    history = data["Windows"][data["Windows"]["Trap ID"].astype(str) == str(trap_id)].copy()

    if history.empty:
        start_time = parse_dt(tr["Deployment Start"])
        if start_time is None:
            raise ValueError("Set a valid deployment date and time before starting the first window.")
    else:
        history["_end"] = history["End Time"].apply(parse_dt)
        closed = history[history["Status"] == "Closed"].copy()
        if effective_time is None:
            raise ValueError(
                "This trap has historical windows. Enter the correct effective time in Administration rather than restarting from deployment."
            )
        start_time = effective_time
        latest_end = closed["_end"].dropna().max() if not closed.empty else None
        if latest_end and start_time < latest_end:
            raise ValueError("The new window cannot start before the latest historical window ended.")

    staged = {name: frame.copy(deep=True) for name, frame in data.items()}
    wid = start_window(staged, trap_id, start_time)
    audit_change(staged, "Trap", trap_id, "Active test window", "", wid, reason)
    save_data(staged)
    for name in data:
        data[name] = staged[name]
    return wid


def move_trap(data, trap_id, destination_site, effective_time, reason, route_order, location, camera_id):
    tr = trap_row(data, trap_id)
    old_site = str(tr["Site ID"])
    if old_site == destination_site:
        raise ValueError("Choose a different destination site.")
    destination = data["Sites"][data["Sites"]["Site ID"] == destination_site]
    if destination.empty or destination.iloc[0]["Status"] != "Active":
        raise ValueError("The destination site must be Active.")
    active_visits = data["Visits"][
        (data["Visits"]["Status"] == "In progress")
        & (data["Visits"]["Site ID"].isin([old_site, destination_site]))
    ]
    if not active_visits.empty:
        raise ValueError("Finish or pause active visits at the source and destination sites before moving this trap.")
    current = open_window(data, trap_id)
    if current is not None:
        idx = data["Windows"].index[data["Windows"]["Window ID"] == current["Window ID"]][0]
        data["Windows"].at[idx, "End Time"] = dtstr(effective_time)
        data["Windows"].at[idx, "Status"] = "Closed"
        data["Windows"].at[idx, "End Reason"] = "Trap moved"
        data["Windows"].at[idx, "Review Status"] = "Not required"
    idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
    data["Traps"].at[idx, "Site ID"] = destination_site
    data["Traps"].at[idx, "Route Order"] = str(route_order)
    data["Traps"].at[idx, "Location"] = location
    data["Traps"].at[idx, "Camera ID"] = camera_id
    new_window = start_window(data, trap_id, effective_time)
    audit_change(data, "Trap", trap_id, "Site ID", old_site, destination_site, reason)
    audit_change(data, "Trap", trap_id, "Route Order", tr["Route Order"], route_order, reason)
    audit_change(data, "Trap", trap_id, "Location", tr["Location"], location, reason)
    save_data(data)
    return new_window


def change_trap_build(data, trap_id, new_product, new_build, effective_time, reason, commit=True):
    tr = trap_row(data, trap_id)
    old_product, old_build = str(tr["Product"]), str(tr["Build Version"])
    if old_product == new_product and old_build == new_build:
        raise ValueError("Choose a different build.")
    current = open_window(data, trap_id)
    if current is not None:
        idx = data["Windows"].index[data["Windows"]["Window ID"] == current["Window ID"]][0]
        data["Windows"].at[idx, "End Time"] = dtstr(effective_time)
        data["Windows"].at[idx, "Status"] = "Closed"
        data["Windows"].at[idx, "End Reason"] = "Build changed"
        data["Windows"].at[idx, "Review Status"] = "Not required"
    idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
    data["Traps"].at[idx, "Product"] = new_product
    data["Traps"].at[idx, "Build Version"] = new_build
    new_window = start_window(data, trap_id, effective_time)
    audit_change(data, "Trap", trap_id, "Build Version", f"{old_product} · {old_build}", f"{new_product} · {new_build}", reason)
    if commit:
        save_data(data)
    return new_window


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


def navigate(page: str, rerun: bool = True, **kwargs):
    """One navigation controller for deliberate page/workflow changes."""
    current_page = st.session_state.get("page")
    context_changed = any(st.session_state.get(key) != value for key, value in kwargs.items())
    destination_changed = current_page != page or context_changed
    st.session_state.page = page
    for key, value in kwargs.items():
        st.session_state[key] = value
    if destination_changed:
        st.session_state.scroll_to_top_once = True
        st.session_state.navigation_sequence = int(st.session_state.get("navigation_sequence", 0)) + 1
    if rerun:
        st.rerun()


def go(page: str, **kwargs):
    navigate(page, rerun=True, **kwargs)


def set_page(page: str, **kwargs):
    """Callback-safe route change; Streamlit reruns automatically."""
    navigate(page, rerun=False, **kwargs)


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
            const topAnchor = doc.getElementById('r1m1-page-top');
            if (topAnchor) {
              try { topAnchor.scrollIntoView({block: 'start', inline: 'nearest', behavior: 'auto'}); } catch (_) {}
            }
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


def pending_check_id_key(visit_id: str, trap_id: str) -> str:
    return f"pending_check_id_{visit_id}_{trap_id}"


def photo_component_event_key(visit_id: str, trap_id: str) -> str:
    return f"photo_component_event_{visit_id}_{trap_id}"


def ensure_pending_check_id(visit_id: str, trap_id: str) -> str:
    """Return a deterministic ID so verified uploads survive a browser refresh."""
    key = pending_check_id_key(visit_id, trap_id)
    expected = deterministic_check_id(visit_id, trap_id)
    if st.session_state.get(key) != expected:
        st.session_state[key] = expected
    return expected


def photo_transaction_context(visit_id: str, trap_id: str, site_id: str, bag_id: str, window_id: str) -> dict:
    return {
        "check_id": ensure_pending_check_id(visit_id, trap_id),
        "visit_id": str(visit_id),
        "trap_id": str(trap_id),
        "site_id": str(site_id),
        "bag_id": str(bag_id or ""),
        "window_id": str(window_id),
    }


def render_check_photo_capture(visit_id: str, trap_id: str, site_id: str, bag_id: str, window_id: str) -> dict:
    """Prepare photos in-browser and persist each selected image before final check save."""
    context = photo_transaction_context(visit_id, trap_id, site_id, bag_id, window_id)
    event_key = photo_component_event_key(visit_id, trap_id)
    verification = verify_pending_photo_transaction(DATA_ROOT, context, MAX_SAVED_PHOTO_BYTES)

    component_value = PHOTO_COMPONENT(
        photos=verification.get("photos", []),
        removed_ids=verification.get("removed_ids", []),
        disabled=False,
        retry_delays_ms=[1000, 2000, 4000],
        max_raw_bytes=MAX_RAW_PHOTO_BYTES,
        max_prepared_bytes=MAX_SAVED_PHOTO_BYTES,
        key=f"critical_photo_upload_{visit_id}_{trap_id}",
        default=None,
    )

    if isinstance(component_value, dict):
        event_id = str(component_value.get("event_id", ""))
        if event_id and event_id != st.session_state.get(event_key):
            st.session_state[event_key] = event_id
            action = str(component_value.get("action", ""))
            try:
                if action != "remove" and component_value.get("selections"):
                    add_expected_photos(DATA_ROOT, context, component_value.get("selections", []))

                for failure in component_value.get("client_failures", []) or []:
                    photo_id = str(failure.get("photo_id", ""))
                    if photo_id:
                        record_failure(
                            DATA_ROOT, context, photo_id,
                            retryable=bool(failure.get("retryable")),
                            error_code=str(failure.get("error_code") or "browser_failure"),
                            user_error=str(failure.get("user_error") or "Upload failed"),
                            manual_required=True,
                            name=str(failure.get("name") or "photo.jpg"),
                            attempt=int(failure.get("attempt") or 0),
                            detail=str(failure.get("detail") or ""),
                        )

                if action == "selection_started":
                    pass

                elif action in {"upload", "retry"}:
                    incoming = component_value.get("photo") or {}
                    photo_id = str(incoming.get("photo_id", ""))
                    if action == "retry" and photo_id:
                        mark_retry_started(DATA_ROOT, context, photo_id)
                    try:
                        store_pending_photo(DATA_ROOT, context, incoming, MAX_SAVED_PHOTO_BYTES)
                    except PhotoPermanentError as exc:
                        record_failure(
                            DATA_ROOT, context, photo_id, retryable=False,
                            error_code="invalid_photo",
                            user_error="This photo could not be prepared. Remove it and select it again.",
                            manual_required=True, name=str(incoming.get("name") or "photo.jpg"),
                            attempt=int(incoming.get("attempt") or 0), detail=str(exc),
                        )
                    except PhotoTransientError as exc:
                        record_failure(
                            DATA_ROOT, context, photo_id, retryable=True,
                            error_code="temporary_upload_failure",
                            user_error="Upload failed", manual_required=False,
                            name=str(incoming.get("name") or "photo.jpg"),
                            attempt=int(incoming.get("attempt") or 0), detail=str(exc),
                        )
                    except Exception as exc:
                        record_failure(
                            DATA_ROOT, context, photo_id, retryable=False,
                            error_code="unexpected_upload_failure",
                            user_error="This photo could not upload. Remove it and select it again.",
                            manual_required=True, name=str(incoming.get("name") or "photo.jpg"),
                            attempt=int(incoming.get("attempt") or 0), detail=str(exc),
                        )

                elif action == "sync_failures":
                    pass

                elif action == "remove":
                    remove_pending_photo(DATA_ROOT, context, str(component_value.get("photo_id", "")))

                st.rerun()
            except (PhotoPermanentError, PhotoTransientError) as exc:
                st.error(f"Photo state could not be updated: {exc}")

    verification = verify_pending_photo_transaction(DATA_ROOT, context, MAX_SAVED_PHOTO_BYTES)
    expected = int(verification.get("expected_count", 0))
    unresolved = max(0, expected - int(verification.get("file_count", 0)))
    return {
        **verification,
        "check_id": context["check_id"],
        "context": context,
        "unresolved_count": unresolved,
    }


def workbook_summary(path: Path) -> Dict[str, int]:
    summary = {}
    try:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str)
        for name in SHEETS:
            summary[name] = len(sheets.get(name, pd.DataFrame()))
    except Exception:
        return {}
    return summary


def available_backups():
    ensure_storage_ready()
    return sorted(
        BACKUP_DIR.glob(f"{DATA_FILE.stem}_*.xlsx"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def restore_backup(backup_path: Path):
    backup_path = Path(backup_path)
    if backup_path.parent.resolve() != BACKUP_DIR.resolve() or not backup_path.exists():
        raise ValueError("The selected backup is not available.")
    # Preserve the current state before restoring anything.
    safety_copy = BACKUP_DIR / (
        f"{DATA_FILE.stem}_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:6]}.xlsx"
    )
    if DATA_FILE.exists():
        shutil.copy2(DATA_FILE, safety_copy)
    temp_restore = DATA_ROOT / f".restore_{uuid.uuid4().hex}.xlsx"
    shutil.copy2(backup_path, temp_restore)
    try:
        # Validate all expected sheets before replacing the live workbook.
        restored = pd.read_excel(temp_restore, sheet_name=None, dtype=str)
        missing = [name for name in SHEETS if name not in restored]
        if missing:
            raise ValueError("Backup is missing sheets: " + ", ".join(missing))
        os.replace(temp_restore, DATA_FILE)
    finally:
        temp_restore.unlink(missing_ok=True)
    return safety_copy


def plan_demo_data_removal(data):
    """Plan removal of bundled demo records without deleting referenced or modified real data."""
    demo_path = APP_DIR / "field_trial_data_v8_6_5.xlsx"
    if not demo_path.exists():
        raise FileNotFoundError("Bundled demo workbook was not found.")
    demo = pd.read_excel(demo_path, sheet_name=None, dtype=str)
    current = {name: frame.fillna("").astype(str).copy() for name, frame in data.items()}
    demo = {name: frame.fillna("").astype(str).copy() for name, frame in demo.items()}
    planned = {name: set() for name in SHEETS}

    id_columns = {
        "Photos": "Photo ID",
        "Followups": "Follow-up ID",
        "Checks": "Check ID",
        "Visits": "Visit ID",
        "Windows": "Window ID",
        "Traps": "Trap ID",
        "Sites": "Site ID",
    }

    # Demo leaf records have stable IDs that real records do not use.
    for sheet in ["Photos", "Followups", "Checks", "Visits", "Windows"]:
        key = id_columns[sheet]
        if key in current[sheet].columns and key in demo.get(sheet, pd.DataFrame()).columns:
            planned[sheet] = set(current[sheet][key]) & set(demo[sheet][key])

    # Protect any demo window referenced by non-demo records or photos.
    protected_windows = set()
    for child, col in [("Checks", "Window Closed"), ("Followups", "Window ID"), ("Photos", "Window ID")]:
        if col not in current[child].columns:
            continue
        child_key = id_columns.get(child)
        for _, row in current[child].iterrows():
            child_id = str(row.get(child_key, ""))
            if child_id not in planned.get(child, set()):
                protected_windows.add(str(row[col]))
    planned["Windows"] -= protected_windows

    # Protect demo visits referenced by non-demo checks/follow-ups.
    protected_visits = set()
    for child in ["Checks", "Followups"]:
        for _, row in current[child].iterrows():
            child_id = str(row.get(id_columns.get(child, ""), ""))
            if child_id not in planned.get(child, set()):
                protected_visits.add(str(row.get("Visit ID", "")))
    planned["Visits"] -= protected_visits

    # Traps and sites may only be removed when nothing remaining references them.
    demo_traps = set(demo.get("Traps", pd.DataFrame()).get("Trap ID", pd.Series(dtype=str)))
    demo_sites = set(demo.get("Sites", pd.DataFrame()).get("Site ID", pd.Series(dtype=str)))
    for trap_id in demo_traps:
        referenced = False
        for child in ["Checks", "Windows", "Followups", "Photos"]:
            if "Trap ID" not in current[child].columns:
                continue
            rows = current[child][current[child]["Trap ID"] == trap_id]
            child_key = id_columns.get(child)
            remaining = rows if not child_key else rows[~rows[child_key].isin(planned.get(child, set()))]
            if not remaining.empty:
                referenced = True
                break
        if not referenced:
            planned["Traps"].add(trap_id)

    for site_id in demo_sites:
        referenced = False
        for child in ["Traps", "Visits", "Windows", "Followups", "Photos"]:
            if "Site ID" not in current[child].columns:
                continue
            rows = current[child][current[child]["Site ID"] == site_id]
            child_key = id_columns.get(child)
            remaining = rows if not child_key else rows[~rows[child_key].isin(planned.get(child, set()))]
            if not remaining.empty:
                referenced = True
                break
        if not referenced:
            planned["Sites"].add(site_id)

    # Builds are retained whenever any current trap/window uses them.
    demo_build_keys = set(
        tuple(row) for row in demo.get("Builds", pd.DataFrame())[["Product", "Build Version"]].itertuples(index=False, name=None)
    ) if not demo.get("Builds", pd.DataFrame()).empty else set()
    used_builds = set()
    for sheet in ["Traps", "Windows"]:
        if {"Product", "Build Version"}.issubset(current[sheet].columns):
            used_builds |= set(tuple(row) for row in current[sheet][["Product", "Build Version"]].itertuples(index=False, name=None))
    planned["Builds"] = demo_build_keys - used_builds

    counts = {name: len(values) for name, values in planned.items()}
    return planned, counts


def commit_demo_data_removal(data, planned, reason):
    """Apply a reviewed demo-removal plan to a copied dataset, then save once."""
    updated = {name: frame.copy(deep=True) for name, frame in data.items()}
    id_columns = {
        "Photos": "Photo ID",
        "Followups": "Follow-up ID",
        "Checks": "Check ID",
        "Visits": "Visit ID",
        "Windows": "Window ID",
        "Traps": "Trap ID",
        "Sites": "Site ID",
    }
    for sheet, ids in planned.items():
        if not ids or sheet not in updated:
            continue
        if sheet == "Builds":
            key_series = updated[sheet][["Product", "Build Version"]].astype(str).apply(tuple, axis=1)
            updated[sheet] = updated[sheet].loc[~key_series.isin(ids)].reset_index(drop=True)
        else:
            key = id_columns.get(sheet)
            if key and key in updated[sheet].columns:
                updated[sheet] = updated[sheet].loc[
                    ~updated[sheet][key].astype(str).isin(ids)
                ].reset_index(drop=True)

    # Referential-integrity proof before commit.
    references = [
        ("Checks", "Visit ID", "Visits", "Visit ID"),
        ("Checks", "Trap ID", "Traps", "Trap ID"),
        ("Checks", "Window Closed", "Windows", "Window ID"),
        ("Windows", "Trap ID", "Traps", "Trap ID"),
        ("Followups", "Visit ID", "Visits", "Visit ID"),
        ("Followups", "Trap ID", "Traps", "Trap ID"),
        ("Followups", "Window ID", "Windows", "Window ID"),
        ("Photos", "Check ID", "Checks", "Check ID"),
        ("Photos", "Window ID", "Windows", "Window ID"),
        ("Photos", "Trap ID", "Traps", "Trap ID"),
    ]
    broken = []
    for child, child_col, parent, parent_col in references:
        if child_col not in updated[child].columns or parent_col not in updated[parent].columns:
            continue
        parent_ids = set(updated[parent][parent_col].astype(str))
        child_ids = set(updated[child][child_col].astype(str)) - {""}
        missing = sorted(child_ids - parent_ids)
        if missing:
            broken.append(f"{child}.{child_col} → {parent}.{parent_col}: {len(missing)} missing")
    if broken:
        raise RuntimeError("Removal blocked because it would break linked records: " + "; ".join(broken))

    audit_change(
        updated,
        "Workbook",
        "FIELD_DATA",
        "Bundled demo data",
        "Present",
        "Removed",
        reason,
    )
    save_data(updated)
    return updated




def remove_followup_task(data, followup_id: str, reason: str):
    """Remove one invalid follow-up without deleting its linked check or test window."""
    if not reason.strip():
        raise ValueError("Enter a reason for removing the follow-up.")
    matches = data["Followups"][data["Followups"]["Follow-up ID"].astype(str) == str(followup_id)]
    if matches.empty:
        raise ValueError("The follow-up task could not be found.")
    task = matches.iloc[0]
    staged = {name: frame.copy(deep=True) for name, frame in data.items()}
    staged["Followups"] = staged["Followups"][
        staged["Followups"]["Follow-up ID"].astype(str) != str(followup_id)
    ].reset_index(drop=True)
    audit_change(
        staged,
        "Follow-up",
        followup_id,
        "Record",
        f"{task['Follow-up Type']} · {task['Trap ID']} · Bag {task['Bag ID']}",
        "Removed",
        reason.strip(),
    )
    refresh_review_status(staged, str(task.get("Window ID", "")))
    save_data(staged)
    for name in data:
        data[name] = staged[name]
    return task


def remove_unused_build(data, product: str, version: str, reason: str):
    """Remove one unreferenced build only."""
    if not reason.strip():
        raise ValueError("Enter a reason for removing the build.")
    used_by_traps = (
        (data["Traps"]["Product"].astype(str) == str(product))
        & (data["Traps"]["Build Version"].astype(str) == str(version))
    ).any()
    used_by_windows = (
        (data["Windows"]["Product"].astype(str) == str(product))
        & (data["Windows"]["Build Version"].astype(str) == str(version))
    ).any()
    if used_by_traps or used_by_windows:
        raise ValueError("This build is still referenced by a trap or test window.")
    staged = {name: frame.copy(deep=True) for name, frame in data.items()}
    mask = (
        (staged["Builds"]["Product"].astype(str) == str(product))
        & (staged["Builds"]["Build Version"].astype(str) == str(version))
    )
    if not mask.any():
        raise ValueError("The build could not be found.")
    staged["Builds"] = staged["Builds"].loc[~mask].reset_index(drop=True)
    audit_change(staged, "Build", f"{product}::{version}", "Record", "Present", "Removed", reason.strip())
    save_data(staged)
    for name in data:
        data[name] = staged[name]


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



def visit_timing_label(data, site_id: str, visit_row) -> str:
    completed = data["Visits"][
        (data["Visits"]["Site ID"] == site_id)
        & (data["Visits"]["Status"] == "Complete")
    ].copy()
    if completed.empty:
        return "First visit"
    completed["_end"] = completed["End Time"].apply(parse_dt)
    current_start = parse_dt(visit_row.get("Start Time", ""))
    prior = completed[completed["_end"].notna()]
    if current_start:
        prior = prior[prior["_end"] < current_start]
    if prior.empty:
        return "First visit"
    previous_end = prior.sort_values("_end").iloc[-1]["_end"]
    site_rows = data["Sites"][data["Sites"]["Site ID"] == site_id]
    planned_days = int(float(site_rows.iloc[0]["Visit Interval Days"] or 3)) if not site_rows.empty else 3
    actual_days = (current_start - previous_end).total_seconds() / 86400 if current_start else planned_days
    if actual_days < planned_days - 0.5:
        return "Early"
    if actual_days > planned_days + 0.5:
        return "Late"
    return "On schedule"


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


def render_compact_card_content(
    *,
    title: str,
    right_label: str = "",
    main_line: str = "",
    meta_line: str = "",
) -> None:
    """Render the shared compact card hierarchy without relying on Streamlit wrappers."""
    right_html = (
        f'<span class="shared-card-label">{html.escape(str(right_label))}</span>'
        if right_label else ""
    )
    main_html = (
        f'<div class="shared-card-main">{html.escape(str(main_line))}</div>'
        if main_line else ""
    )
    meta_html = (
        f'<div class="shared-card-meta">{html.escape(str(meta_line))}</div>'
        if meta_line else ""
    )
    st.markdown(
        '<div class="shared-card-copy">'
        '<div class="shared-card-heading">'
        f'<strong>{html.escape(str(title))}</strong>{right_html}'
        '</div>'
        f'{main_html}{meta_html}'
        '</div>',
        unsafe_allow_html=True,
    )


def render_visit_trap_card(tr, checked: bool, visit_id: str, site_id: str) -> None:
    """Compact field card with one checked-state indicator."""
    trap_id = str(tr["Trap ID"])
    product_build = f"{tr['Product']} · {tr['Build Version']}"
    location = trap_location_label(tr)
    route = str(tr["Route Order"] or "—")

    if checked:
        st.markdown(
            '<div class="visit-trap-card is-checked">'
            '<div class="visit-trap-copy">'
            f'<div class="visit-trap-line"><strong>{html.escape(trap_id)}</strong><strong class="visit-trap-status">✓ Checked</strong></div>'
            f'<div class="visit-trap-line"><span>{html.escape(location)}</span><span class="visit-trap-meta">{html.escape(product_build)}</span></div>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    with app_card():
        render_compact_card_content(
            title=trap_id,
            right_label=location,
            main_line=product_build,
            meta_line=f"Route {route} · Not checked",
        )
        if st.button("Check", key=f"visit_check_{visit_id}_{trap_id}", use_container_width=True):
            go("check", site_id=site_id, visit_id=visit_id, trap_id=trap_id)


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
header[data-testid="stHeader"] {
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
}/* App sidebar controls must remain visible on a light header. */

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
[data-testid="collapsedControl"], button[kind="header"] {
  background: #ffffff !important;
  color: #202124 !important;
  opacity: 1 !important;
  visibility: visible !important;
  z-index: 1002 !important;
}
[data-testid="collapsedControl"] *, button[kind="header"] * {
  color: #202124 !important;
  fill: #202124 !important;
  stroke: #202124 !important;
  opacity: 1 !important;
}

@media (max-width: 700px) {
[data-testid="collapsedControl"], button[kind="header"] {
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
header[data-testid="stHeader"] [data-testid="collapsedControl"], header[data-testid="stHeader"] button[aria-label*="menu" i] {
    color: #444a53 !important;
    background: #ffffff !important;
    opacity: 1 !important;
  }
header[data-testid="stHeader"] [data-testid="collapsedControl"] svg, header[data-testid="stHeader"] button[aria-label*="menu" i] svg {
    color: #444a53 !important;
    fill: none !important;
    stroke: #444a53 !important;
    opacity: 1 !important;
  }
header[data-testid="stHeader"] [data-testid="collapsedControl"] svg *, header[data-testid="stHeader"] button[aria-label*="menu" i] svg * {
    color: #444a53 !important;
    stroke: #444a53 !important;
    opacity: 1 !important;
  }
}

/* v8.6.66 — force all mobile navigation chevron geometry to dark grey. */
@media (max-width: 768px) {
header[data-testid="stHeader"] button, [data-testid="collapsedControl"], [data-testid="stSidebar"] details > summary {
    color: #444a53 !important;
  }
header[data-testid="stHeader"] button svg, [data-testid="collapsedControl"] svg, [data-testid="stSidebar"] details > summary svg {
    color: #444a53 !important;
    opacity: 1 !important;
  }
header[data-testid="stHeader"] button svg path, header[data-testid="stHeader"] button svg polyline, header[data-testid="stHeader"] button svg line, [data-testid="collapsedControl"] svg path, [data-testid="collapsedControl"] svg polyline, [data-testid="collapsedControl"] svg line, [data-testid="stSidebar"] details > summary svg path, [data-testid="stSidebar"] details > summary svg polyline, [data-testid="stSidebar"] details > summary svg line {
    stroke: #444a53 !important;
    color: #444a53 !important;
    opacity: 1 !important;
  }
header[data-testid="stHeader"] button svg path[fill]:not([fill="none"]), [data-testid="collapsedControl"] svg path[fill]:not([fill="none"]), [data-testid="stSidebar"] details > summary svg path[fill]:not([fill="none"]) {
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


/* v8.6.71 — app sidebar controls only. Do not style Streamlit toolbar/settings. */
@media (max-width: 768px) {/* Collapsed app menu control at the far left of the header. *//* Open drawer: keep one native close control only. */

  /* Administration expander: no white icon box, chevron aligned right. */
  [data-testid="stSidebar"] details > summary {
    position: relative !important;
    background: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
    padding-right: 2.25rem !important;
  }

  [data-testid="stSidebar"] details > summary svg {
    display: none !important;
  }

  [data-testid="stSidebar"] details > summary::after {
    content: "";
    position: absolute;
    right: .85rem;
    top: 50%;
    width: .52rem;
    height: .52rem;
    border-right: 2px solid #444a53;
    border-bottom: 2px solid #444a53;
    transform: translateY(-65%) rotate(45deg);
    pointer-events: none;
  }

  [data-testid="stSidebar"] details[open] > summary::after {
    transform: translateY(-35%) rotate(225deg);
  }

  /* Explicitly leave Streamlit's settings/toolbar control untouched. */
  header[data-testid="stHeader"] button {
    background: initial !important;
  }
}

/* Hide only the Streamlit menu container. Never target menu-labelled buttons:
   Streamlit uses that accessible label for the mobile sidebar control. */
[data-testid="stMainMenu"],
#MainMenu {
  display: none !important;
  visibility: hidden !important;
  pointer-events: none !important;
}


/* v8.7.4 — stable field completion components */
.visit-trap-card {
  display: grid;
  grid-template-columns: minmax(9rem, 1fr) minmax(12rem, 1.7fr) 3.25rem;
  align-items: center;
  gap: 1rem;
  min-height: 7.1rem;
  margin: 0 0 1rem 0;
  padding: 1rem 1.1rem;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #ffffff;
  box-sizing: border-box;
}
.visit-trap-card.is-checked {
  background: #eef8f1;
  border-color: #b9ddc5;
}
.visit-trap-id,
.visit-trap-location { color: var(--text); font-weight: 700; }
.visit-trap-meta { color: var(--muted); margin-top: .35rem; }
.visit-trap-status { color: #22683d; font-weight: 700; margin-top: .35rem; }
.visit-trap-checkmark { color: #22683d; font-size: 1.35rem; font-weight: 800; text-align: center; }
@media (max-width: 700px) {
  .visit-trap-card {
    grid-template-columns: minmax(7.5rem, 1fr) minmax(8rem, 1.35fr) 2.5rem;
    min-height: 6.4rem;
    gap: .7rem;
    padding: .9rem;
  }
}
.photo-tile img {
  width: 64px !important;
  height: 64px !important;
  object-fit: cover !important;
  border-radius: 8px !important;
}

/* v8.7.3 — force one complete light visual system */
html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"],
[data-testid="stMain"], [data-testid="stHeader"], [data-testid="stSidebar"],
[data-testid="stSidebar"] > div {
  background: #ffffff !important;
  color: #25262d !important;
  color-scheme: light !important;
}

input, textarea, select,
[data-baseweb="select"] > div,
[data-baseweb="input"] > div,
[data-baseweb="textarea"] > div,
[data-testid="stFileUploader"],
[data-testid="stExpander"],
[data-testid="stDataFrame"],
[data-testid="stTable"] {
  background: #ffffff !important;
  color: #25262d !important;
  border-color: #d7d9dd !important;
}

[data-baseweb="popover"],
[data-baseweb="menu"],
ul[role="listbox"],
li[role="option"] {
  background: #ffffff !important;
  color: #25262d !important;
}

li[role="option"]:hover,
li[role="option"][aria-selected="true"] {
  background: #fff1e8 !important;
  color: #25262d !important;
}

[data-testid="stTabs"] button,
[data-testid="stTabs"] button p,
[data-baseweb="tab-list"] button,
[data-baseweb="tab-list"] button p {
  color: #444a53 !important;
  background: transparent !important;
  opacity: 1 !important;
}

[data-testid="stTabs"] button[aria-selected="true"],
[data-baseweb="tab-list"] button[aria-selected="true"] {
  color: #f36c21 !important;
}

[data-testid="stRadio"] label,
[data-testid="stCheckbox"] label,
[data-testid="stRadio"] p,
[data-testid="stCheckbox"] p {
  color: #25262d !important;
}

[data-testid="stDataFrame"] *,
[data-testid="stTable"] * {
  color-scheme: light !important;
}

button[kind="secondary"],
[data-testid="stBaseButton-secondary"] {
  background: #ffffff !important;
  color: #25262d !important;
  border-color: #d7d9dd !important;
}
button[kind="secondary"]:hover,
[data-testid="stBaseButton-secondary"]:hover {
  background: #f7f7f5 !important;
  color: #25262d !important;
}
[data-baseweb="tab-list"],
[data-baseweb="tab-panel"],
[data-testid="stRadio"],
[data-testid="stCheckbox"] {
  background: transparent !important;
  color: #25262d !important;
}


/* v8.7.5.2 — shared card system and single drawer control.
   This final layer intentionally overrides earlier page-specific card geometry. */
:root {
  --card-bg: #f3f3f0;
  --card-border: #d7d9dd;
  --card-success-bg: #eef8f1;
  --card-success-border: #b9ddc5;
}

/* All app-owned record/task cards share one neutral surface. */
[data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker),
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .app-card-marker),
div[data-testid="stVerticalBlock"]:has(> div.element-container .app-card-marker),
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) {
  background: var(--card-bg) !important;
  border: 1px solid var(--card-border) !important;
  border-radius: 14px !important;
  box-shadow: none !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker) > div,
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) > div {
  padding: .9rem 1rem !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.site-complete-marker) {
  background: var(--card-success-bg) !important;
  border-color: var(--card-success-border) !important;
}

.shared-card-copy { display:grid; gap:.32rem; width:100%; margin:0 0 .35rem 0; }
.shared-card-heading { display:flex; justify-content:space-between; align-items:baseline; gap:.75rem; }
.shared-card-heading strong { color:var(--text); font-size:1rem; }
.shared-card-main { color:var(--text); font-size:.95rem; }
.shared-card-meta { color:var(--muted); font-size:.86rem; line-height:1.4; }
.shared-card-label { color:var(--text); font-size:.88rem; text-align:right; }
.shared-card-status { font-size:.88rem; font-weight:700; text-align:right; white-space:nowrap; }
.shared-card-status.is-complete { color:#22683d; }
.shared-card-status.is-progress { color:#2f5f8f; }
.shared-card-status.is-warning { color:#75530b; }

/* Field cards use the same neutral base and identical geometry between states. */
.visit-trap-card,
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) {
  background:var(--card-bg) !important;
}
.visit-trap-card.is-checked {
  background:var(--card-success-bg) !important;
  border-color:var(--card-success-border) !important;
}
.visit-trap-card { padding:.9rem 1rem !important; margin-bottom:.7rem !important; min-height:0 !important; }

/* Compact action spacing inside all shared cards. */
[data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker) .stButton,
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) .stButton {
  margin-top:.35rem !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker) .stButton button,
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) .stButton button {
  min-height:2.7rem !important;
}/* Exactly one app-owned drawer-close chevron. Hide every native drawing layer. */

@media (max-width:700px) {
  [data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker) > div,
  [data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) > div,
  .visit-trap-card { padding:.8rem .9rem !important; }
  .shared-card-heading { gap:.5rem; }
  .shared-card-heading strong { font-size:.96rem; }
  .shared-card-main { font-size:.9rem; }
  .shared-card-meta, .shared-card-label, .shared-card-status { font-size:.82rem; }
}
</style>
""", unsafe_allow_html=True)


# v8.7.5 system-level visual repair. This is intentionally the final CSS layer.
st.markdown("""
<style>
:root, html, body { color-scheme: only light !important; }
[data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"],
[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stSidebar"] > div {
  background: #fff !important; color: #25262d !important;
}
header[data-testid="stHeader"] { border: 0 !important; box-shadow: none !important; }
header[data-testid="stHeader"]::before, header[data-testid="stHeader"]::after { display:none !important; }

/* Native controls: force readable light surfaces, including iOS dark preference. */
input, textarea, select, button,
[data-baseweb="input"], [data-baseweb="input"] > div,
[data-baseweb="textarea"], [data-baseweb="textarea"] > div,
[data-baseweb="select"], [data-baseweb="select"] > div,
[data-baseweb="base-input"], [data-baseweb="base-input"] > div,
[data-testid="stFileUploader"], [data-testid="stFileUploader"] section,
[data-testid="stFileUploader"] section > div,
[data-testid="stExpander"], [data-testid="stExpander"] details,
[data-testid="stExpander"] summary,
[data-testid="stDateInput"], [data-testid="stTimeInput"] {
  color-scheme: only light !important;
  background-color: #fff !important;
  color: #25262d !important;
}
[data-testid="stFileUploader"] section { border-color:#d7d9dd !important; }
[data-testid="stFileUploader"] small, [data-testid="stFileUploader"] span,
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * { color:#25262d !important; }
[data-testid="stTimeInput"] input, [data-testid="stDateInput"] input { background:#fff !important; color:#25262d !important; }/* Keep app navigation controls visible in every state. */
[data-testid="stSidebar"] details > summary svg { display:initial !important; visibility:visible !important; opacity:1 !important; color:#25262d !important; }
[data-testid="stSidebar"] details > summary svg * { stroke:#25262d !important; }
[data-testid="stSidebar"] details > summary::after { content:none !important; display:none !important; }/* v8.7.5.1 — controlled menu-chevron repair.
   App-owned icons avoid Streamlit SVG colour/shape regressions.
   Applies on desktop and mobile; never targets generic header buttons. *//* Hide only the two native sidebar-control SVGs. *//* Closed drawer: right-pointing open chevron. *//* Avoid two pseudo-icons where Streamlit wraps the button. *//* Open drawer: left-pointing close chevron. *//* Maintain visible controls without hover-dependent colour changes. */

/* Compact field cards. */
.visit-trap-card { min-height:0 !important; padding:.9rem 1rem !important; display:block !important; margin-bottom:.7rem !important; }
.visit-trap-copy { display:grid; gap:.35rem; width:100%; }
.visit-trap-line { display:flex; justify-content:space-between; align-items:baseline; gap:1rem; }
.visit-trap-meta { color:#737780; font-size:.9rem; }
.visit-trap-status { color:#22683d; white-space:nowrap; }
.visit-trap-card.is-checked { background:#eef8f1 !important; border-color:#b9ddc5 !important; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) { margin-bottom:.7rem !important; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) > div { padding:.85rem 1rem !important; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) .stButton button { min-height:2.7rem !important; margin-top:.45rem !important; }

/* Completed site state and compact site metadata. */
[data-testid="stVerticalBlockBorderWrapper"]:has(.site-complete-marker) { background:#eef8f1 !important; border-color:#b9ddc5 !important; }
.site-card-compact { display:grid; gap:.35rem; }
.site-card-heading { display:flex; justify-content:space-between; gap:1rem; align-items:baseline; font-size:1.05rem; }
.site-card-status { color:#22683d; font-size:.9rem; font-weight:700; white-space:nowrap; }
.site-card-meta { color:#737780; font-size:.9rem; }

/* v8.7.6.6 photo layout is isolated inside the custom component iframe. */

@media (max-width:700px) {
  .block-container { padding-top:calc(5rem + env(safe-area-inset-top)) !important; }
  h1 { font-size:2.35rem !important; line-height:1.05 !important; }
  .visit-trap-line, .site-card-heading { gap:.55rem; }
  .visit-trap-meta, .site-card-meta { font-size:.82rem; }
  [data-testid="stVerticalBlockBorderWrapper"] { margin-bottom:.75rem !important; }
}/* v8.7.5.3 — controlled single-chevron fix.
   Draw exactly one icon on the actual button only. Container and nested pseudo-elements
   are explicitly suppressed so wrapper differences cannot create a doubled glyph. */

/* v8.7.5.4 — targeted shared base for the two missed trap-card surfaces only.
   Other card pages are intentionally untouched. */
.setup-trap-card-marker { display:none !important; }

[data-testid="stVerticalBlockBorderWrapper"]:has(.setup-trap-card-marker),
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) {
  background:#f3f3f0 !important;
  border:1px solid #d7d9dd !important;
  border-radius:14px !important;
  box-shadow:none !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.setup-trap-card-marker) > div,
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) > div {
  padding:.85rem 1rem !important;
}

/* Streamlit wrapper fallback for mobile DOM variants. Keep the selector limited to
   a bordered block containing one of the two page-specific markers. */
div[data-testid="stVerticalBlock"]:has(.setup-trap-card-marker)[style*="border"],
div[data-testid="stVerticalBlock"]:has(.visit-unchecked-marker)[style*="border"] {
  background:#f3f3f0 !important;
  border-color:#d7d9dd !important;
  border-radius:14px !important;
  box-shadow:none !important;
}

@media (max-width:700px) {
  [data-testid="stVerticalBlockBorderWrapper"]:has(.setup-trap-card-marker),
  [data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) {
    margin-bottom:.7rem !important;
  }
  [data-testid="stVerticalBlockBorderWrapper"]:has(.setup-trap-card-marker) > div,
  [data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) > div {
    padding:.8rem .9rem !important;
  }
  [data-testid="stVerticalBlockBorderWrapper"]:has(.setup-trap-card-marker) .shared-card-copy {
    gap:.28rem !important;
    margin-bottom:.2rem !important;
  }
}/* v8.7.5.6 — final drawer-control isolation.
   Some Streamlit builds render an underlying double-arrow text glyph. Suppress
   all native button content, then draw one app-owned chevron on the button. *//* v8.7.5.10 — closed-menu control across both Streamlit DOM forms.
   On some deployments the test-id element is the clickable control itself;
   on others it wraps a nested button. Draw exactly one chevron in either case.
   The working open-drawer control is intentionally untouched. *//* Direct-control form: suppress native content only when there is no nested button. *//* Remove earlier container pseudo-elements, then restore exactly one for
   the direct-control DOM form. *//* Nested-button form: keep the proven button implementation and make sure the
   wrapper itself cannot draw a second icon. */

</style>

<style>/* v8.7.5.12 — single closed-menu implementation for Streamlit 1.60.0.
   Open-drawer control rules are retained separately. */

/* Login page only. */
body:has(.login-page-marker) [data-testid="stMainBlockContainer"] {
  max-width:30rem !important;
  margin:0 auto !important;
  padding:clamp(2rem, 10vh, 7rem) 1.25rem 2rem !important;
}
.login-page-marker { display:none !important; }

body:has(.login-page-marker) [data-testid="stImage"] {
  margin:0 0 1.4rem 0 !important;
}
body:has(.login-page-marker) [data-testid="stImage"] img {
  display:block !important;
  width:13.75rem !important;
  max-width:70vw !important;
  height:auto !important;
}
.login-title {
  margin:0 0 .65rem !important;
  color:#25262d !important;
  font-size:clamp(2.35rem, 6vw, 3.5rem) !important;
  line-height:.98 !important;
  letter-spacing:-.035em !important;
}
.login-intro,
.login-security {
  margin:0 !important;
  color:#737780 !important;
  font-size:1rem !important;
  line-height:1.45 !important;
}
.login-intro { margin-bottom:1rem !important; }
.login-security {
  margin-top:1rem !important;
  font-size:.9rem !important;
}

body:has(.login-page-marker) form[data-testid="stForm"] {
  background:#f3f3f0 !important;
  border:1px solid #d7d9dd !important;
  border-radius:14px !important;
  box-shadow:none !important;
  padding:1rem !important;
}
body:has(.login-page-marker) [data-testid="stTextInput"] > div > div,
body:has(.login-page-marker) [data-testid="stTextInput"] input,
body:has(.login-page-marker) [data-testid="stTextInput"] button {
  background:#fff !important;
  color:#25262d !important;
}
body:has(.login-page-marker) [data-testid="stTextInput"] > div > div {
  border-color:#b9bdc4 !important;
}
body:has(.login-page-marker) [data-testid="stTextInput"] button {
  border:0 !important;
  box-shadow:none !important;
}
body:has(.login-page-marker) [data-testid="stFormSubmitButton"] button {
  width:100% !important;
  background:#f36c21 !important;
  border:1px solid #f36c21 !important;
  color:#fff !important;
  box-shadow:none !important;
}
body:has(.login-page-marker) [data-testid="stFormSubmitButton"] button:hover {
  background:#d95b15 !important;
  border-color:#d95b15 !important;
}

@media (max-width:700px) {
  body:has(.login-page-marker) [data-testid="stMainBlockContainer"] {
    max-width:none !important;
    padding:4rem 1rem 1.5rem !important;
  }
  .login-title { font-size:2.65rem !important; }
  body:has(.login-page-marker) form[data-testid="stForm"] {
    padding:.9rem !important;
  }
}
</style>

<style>
/* v8.7.5.13 — authoritative page rhythm after removal of the retired field-pilot banner.
   Keep only normal Streamlit-header and menu-control clearance. */
body:not(:has(.login-page-marker)) [data-testid="stMainBlockContainer"] {
  padding-top:3.25rem !important;
}

@media (max-width:700px) {
  body:not(:has(.login-page-marker)) [data-testid="stMainBlockContainer"] {
    padding-top:calc(3.75rem + env(safe-area-inset-top)) !important;
  }
}
</style>

<style>
/* v8.7.6.4 — one responsive navigation flow */
.st-key-app_top_navigation {
  width: 100%;
}

.st-key-app_top_navigation [data-testid="stHorizontalBlock"] {
  width: 100%;
  flex-wrap: wrap !important;
  align-items: center !important;
  column-gap: .4rem !important;
  row-gap: .42rem !important;
}

.st-key-app_top_navigation [data-testid="stPageLink"] a,
.st-key-app_top_navigation [data-testid="stPopover"] > button {
  width: auto !important;
  min-height: 2.55rem !important;
  padding: .42rem .85rem !important;
  border: 1px solid #d7d9dd !important;
  border-radius: 999px !important;
  background: #ffffff !important;
  color: #25262d !important;
  box-shadow: none !important;
  font-weight: 500 !important;
  line-height: 1.2 !important;
  white-space: nowrap !important;
}

/* Streamlit's react-aria nav-link text sits in a nested span carrying its own
   hardcoded dark-theme colour, which wins over the <a> rule above through
   normal inheritance rules regardless of !important. Target it directly. */
.st-key-app_top_navigation [data-testid="stPageLink"] a *,
.st-key-app_top_navigation [data-testid="stPopover"] > button * {
  color: #25262d !important;
}

.st-key-app_top_navigation [data-testid="stPageLink"] a:hover,
.st-key-app_top_navigation [data-testid="stPopover"] > button:hover {
  border-color: #b8bcc2 !important;
  background: #f7f7f5 !important;
}

.st-key-app_top_navigation [data-testid="stPageLink"] a[aria-disabled="true"],
.st-key-app_top_navigation [data-testid="stPageLink"] a[aria-disabled="true"] * {
  background: #f3f3f0 !important;
  border-color: #b8bcc2 !important;
  color: #25262d !important;
  opacity: 1 !important;
}

@media (max-width: 700px) {
  .st-key-app_top_navigation [data-testid="stHorizontalBlock"] {
    column-gap: .32rem !important;
    row-gap: .38rem !important;
  }

  .st-key-app_top_navigation [data-testid="stPageLink"] a,
  .st-key-app_top_navigation [data-testid="stPopover"] > button {
    min-height: 2.65rem !important;
    padding: .43rem .72rem !important;
  }
}
</style>

<style>
/* Dark-mode leak fix for Streamlit's react-aria-based widgets (popover panel,
   Material icons, native radio/checkbox). These ship their own colours that
   bypass the app's light-theme CSS, which was written against the older
   BaseWeb widget markup and only reaches container-level elements, not these
   deeply-nested ones. See STYLE_GUIDE.md "Forms and controls": unselected
   controls must be white/dark-outline, never solid black or theme-dependent. */

/* Popover panel (e.g. Administration menu): no existing rule covered the
   panel body itself, only its trigger button, so it fell back to Streamlit's
   built-in dark theme (#0E1117 background, #FAFAFA text). */
[data-testid="stPopoverBody"] {
  background: #ffffff !important;
  color: #25262d !important;
  border: 1px solid #d7d9dd !important;
}
[data-testid="stPopoverBody"] * {
  color: #25262d !important;
}
[data-testid="stPopoverBody"] button[kind="secondary"],
[data-testid="stPopoverBody"] [data-testid="stBaseButton-secondary"] {
  background: #ffffff !important;
  border-color: #d7d9dd !important;
}

/* Material icon glyphs (accordion/expander chevrons etc.) render as text
   ligatures in their own span; force them to the app text colour everywhere
   so none can inherit a stray dark-theme value. */
[data-testid="stIconMaterial"] {
  color: #25262d !important;
}

/* Native radio/checkbox: computed color-scheme is correct (verified via
   devtools), but Chromium's native widget painter still renders the
   unchecked state using the OS dark theme regardless. Native form-control
   theming is unreliable across browsers for this, so stop depending on it.
   Root cause (confirmed by inspecting the live DOM): react-aria wraps the
   real <input> in a "visually hidden" span (overflow:hidden, 1x1px) for
   accessibility, and draws the control everyone actually sees as separate
   decorative divs layered next to it, each carrying Streamlit's hardcoded
   dark-theme colours. Restyling the <input> itself can never work — it is
   permanently clipped to 1px regardless of any CSS applied to it. Instead:
   neutralise every one of Streamlit's decorative divs (colour and layout
   footprint) and draw the entire indicator ourselves via ::before/::after
   on the one stable, testid-anchored ancestor, using :has(input:checked)
   for state. This depends on nothing native or theme-related, so it holds
   across Chrome, Safari and any OS/browser dark-mode setting. */
/* Colour only — do not touch size/margin/padding here. react-aria's press
   handling depends on these divs' actual geometry for its hit-region
   calculation; collapsing them to 0x0 silently broke click/check entirely
   (confirmed: Playwright's force-click stopped toggling state). */
[data-testid="stRadioOption"] div,
[data-testid="stCheckbox"] > label div {
  background-color: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

/* position:relative only — deliberately not display:flex (broke the
   label's text children into flex items, stacking letters one per line)
   and no added padding-left: the label already reserves space for the
   original (still same-sized, now just transparent) decorative divs, so
   the indicator below is placed directly in that existing gap rather than
   pushing the text out further. */
[data-testid="stRadioOption"],
[data-testid="stCheckbox"] > label {
  position: relative !important;
}

[data-testid="stRadioOption"]::before,
[data-testid="stCheckbox"] > label::before {
  content: "" !important;
  position: absolute !important;
  left: 0 !important;
  top: 50% !important;
  transform: translateY(-50%) !important;
  box-sizing: border-box !important;
  width: 18px !important;
  height: 18px !important;
  border: 2px solid #25262d !important;
  background: #ffffff !important;
}
[data-testid="stRadioOption"]::before {
  border-radius: 50% !important;
}
[data-testid="stCheckbox"] > label::before {
  border-radius: 4px !important;
}

[data-testid="stRadioOption"]:has(input:checked)::before,
[data-testid="stCheckbox"] > label:has(input:checked)::before {
  border-color: #f36c21 !important;
}
[data-testid="stCheckbox"] > label:has(input:checked)::before {
  background: #f36c21 !important;
}

/* Orange centre dot for a checked radio. */
[data-testid="stRadioOption"]:has(input:checked)::after {
  content: "" !important;
  position: absolute !important;
  left: 5px !important;
  top: 50% !important;
  width: 8px !important;
  height: 8px !important;
  border-radius: 50% !important;
  background: #f36c21 !important;
  transform: translateY(-50%) !important;
}
/* White checkmark for a checked checkbox. */
[data-testid="stCheckbox"] > label:has(input:checked)::after {
  content: "" !important;
  position: absolute !important;
  left: 6px !important;
  top: 45% !important;
  width: 5px !important;
  height: 9px !important;
  border: solid #ffffff !important;
  border-width: 0 2px 2px 0 !important;
  transform: translateY(-60%) rotate(45deg) !important;
}

[data-testid="stRadioOption"]:has(input:disabled)::before,
[data-testid="stCheckbox"] > label:has(input:disabled)::before {
  opacity: .5 !important;
}
</style>





""", unsafe_allow_html=True)

components.html("""
<script>
(() => {
  const doc = window.parent.document;
  doc.documentElement.style.colorScheme = 'light';
  doc.body.style.colorScheme = 'light';
  let meta = doc.querySelector('meta[name="color-scheme"]');
  if (!meta) { meta = doc.createElement('meta'); meta.name = 'color-scheme'; doc.head.appendChild(meta); }
  meta.content = 'only light';
})();
</script>
""", height=0, width=0)

require_authentication()

data = load_data()
if not st.session_state.get("photo_cleanup_done"):
    cleanup_stale_transactions(DATA_ROOT, data["Checks"]["Check ID"].astype(str).tolist())
    st.session_state.photo_cleanup_done = True
if "page" not in st.session_state: st.session_state.page = "sites"
if "field_operator" not in st.session_state: st.session_state.field_operator = "Jake"

WORKFLOW_PAGES = {"site", "start_visit", "visit", "check", "check_confirm"}


def select_top_navigation(target: str, allowed_pages: set[str]) -> None:
    """Sync framework top navigation with the app's existing workflow router."""
    current = st.session_state.get("page", "sites")
    if current not in allowed_pages:
        st.session_state.page = target
        st.session_state.scroll_to_top_once = True
        st.session_state.navigation_sequence = int(st.session_state.get("navigation_sequence", 0)) + 1


def top_nav_trap_sites() -> None:
    select_top_navigation("sites", {"sites", "site", "start_visit", "visit", "check", "check_confirm"})


def top_nav_traps() -> None:
    select_top_navigation("network", {"network", "trap_detail"})


def top_nav_followups() -> None:
    select_top_navigation("followups", {"followups"})


def top_nav_performance() -> None:
    select_top_navigation("results", {"results"})


def top_nav_trial_setup() -> None:
    select_top_navigation("setup", {"setup", "trap_edit"})


def top_nav_data_records() -> None:
    select_top_navigation("data_management", {"data_management", "windows"})


def top_nav_sign_out() -> None:
    st.session_state.clear()
    st.rerun()


PAGE_TRAP_SITES = st.Page(
    top_nav_trap_sites, title="Trap sites", url_path="trap-sites", default=True
)
PAGE_TRAPS = st.Page(top_nav_traps, title="Traps", url_path="traps")
PAGE_FOLLOWUPS = st.Page(top_nav_followups, title="Follow-ups", url_path="follow-ups")
PAGE_PERFORMANCE = st.Page(
    top_nav_performance, title="Trial performance", url_path="trial-performance"
)
PAGE_TRIAL_SETUP = st.Page(
    top_nav_trial_setup, title="Trial setup", url_path="trial-setup"
)
PAGE_DATA_RECORDS = st.Page(
    top_nav_data_records, title="Data & records", url_path="data-records"
)
PAGE_SIGN_OUT = st.Page(top_nav_sign_out, title="Sign out", url_path="sign-out")

NAVIGATION_PAGES = {
    "": [PAGE_TRAP_SITES, PAGE_TRAPS, PAGE_FOLLOWUPS, PAGE_PERFORMANCE],
    "Administration": [PAGE_TRIAL_SETUP, PAGE_DATA_RECORDS, PAGE_SIGN_OUT],
}

# Keep Streamlit's supported page router, but do not render its responsive
# navigation shell. The app-owned controls below use st.switch_page, so
# routing, URLs and browser history remain framework-owned.
selected_navigation_page = st.navigation(NAVIGATION_PAGES, position="hidden")
selected_navigation_page.run()

PRIMARY_SECTION_BY_APP_PAGE = {
    "sites": "Trap sites",
    "site": "Trap sites",
    "start_visit": "Trap sites",
    "visit": "Trap sites",
    "check": "Trap sites",
    "check_confirm": "Trap sites",
    "network": "Traps",
    "trap_detail": "Traps",
    "followups": "Follow-ups",
    "results": "Trial performance",
}

current_primary_section = PRIMARY_SECTION_BY_APP_PAGE.get(
    st.session_state.get("page", "sites")
)

# Native Streamlit page links and Administration share one wrapping container.
# No selection state is stored, so a tap routes immediately.
with st.container(
    horizontal=True,
    horizontal_alignment="left",
    gap="small",
    width="stretch",
    key="app_top_navigation",
):
    st.page_link(
        PAGE_TRAP_SITES,
        label="Trap sites",
        disabled=current_primary_section == "Trap sites",
        width="content",
    )
    st.page_link(
        PAGE_TRAPS,
        label="Traps",
        disabled=current_primary_section == "Traps",
        width="content",
    )
    st.page_link(
        PAGE_FOLLOWUPS,
        label="Follow-ups",
        disabled=current_primary_section == "Follow-ups",
        width="content",
    )
    st.page_link(
        PAGE_PERFORMANCE,
        label="Trial performance",
        disabled=current_primary_section == "Trial performance",
        width="content",
    )
    with st.popover("Administration"):
        st.page_link(PAGE_TRIAL_SETUP, label="Trial setup", width="stretch")
        st.page_link(PAGE_DATA_RECORDS, label="Data & records", width="stretch")
        st.divider()
        if st.button("Sign out", key="top_nav_sign_out", use_container_width=True):
            st.session_state.clear()
            st.rerun()

# Workflow pages retain one explicit escape route while the top navigation
# remains on the parent Trap sites section.
if st.session_state.page in WORKFLOW_PAGES:
    site_id = st.session_state.get("site_id", "")
    if site_id:
        st.caption(site_name(data, site_id))
    if st.button("Exit to Trap sites", key="exit_workflow_to_sites"):
        go("sites")

st.markdown('<div id="r1m1-page-top" aria-hidden="true"></div>', unsafe_allow_html=True)
page = st.session_state.page
show_flash()

is_demo_data = any(data[name].astype(str).apply(lambda col: col.str.contains("synthetic|sample", case=False, na=False)).any().any() for name in ["Sites", "Windows"] if not data[name].empty)
if is_demo_data:
    message_panel("warning", "Demo data", ["This app contains synthetic demonstration records. Do not treat its Performance figures as trial evidence."])

if page == "sites":
    header("Trap sites", "Choose the trap site you are visiting today.")
    active_sites = data["Sites"][data["Sites"]["Status"] == "Active"].copy()
    if active_sites.empty:
        helper("No active trap sites are available. Reactivate a site in Administration → Trial setup.")
    for _, s in active_sites.iterrows():
        sid = s["Site ID"]
        traps = data["Traps"][(data["Traps"]["Site ID"] == sid) & (data["Traps"]["Status"] == "Active")]
        active = active_visit(data, sid); last = latest_completed_visit(data, sid)
        interval = int(float(s["Visit Interval Days"] or 3)); last_dt = parse_dt(last["End Time"]) if last is not None else None
        next_dt = last_dt + timedelta(days=interval) if last_dt else now()
        completed_today = bool(last_dt and last_dt.date() == now().date())
        checks = data["Checks"][data["Checks"]["Visit ID"] == active["Visit ID"]] if active is not None else pd.DataFrame()
        active_complete = active is not None and len(traps) > 0 and len(checks) >= len(traps)
        if active is not None:
            status_text = "Ready to finish" if active_complete else "In progress"
            status_class = "is-warning" if active_complete else "is-progress"
        elif completed_today:
            status_text = "Last checked today"
            status_class = "is-complete"
        else:
            status_text = ""
            status_class = ""
        with app_card():
            if completed_today and active is None:
                st.markdown('<span class="site-complete-marker" aria-hidden="true"></span>', unsafe_allow_html=True)
            st.markdown(
                '<div class="shared-card-copy site-card-compact">'
                f'<div class="shared-card-heading"><strong>{html.escape(str(s["Site Name"]))}</strong><span class="shared-card-status {status_class}">{html.escape(status_text)}</span></div>'
                f'<div class="shared-card-meta">{len(traps)} active traps · Every {interval} days</div>'
                f'<div class="shared-card-meta">Last {last_dt.strftime("%d %b %Y") if last_dt else "not completed"} · Next {"due now" if next_dt.date() <= now().date() else next_dt.strftime("%d %b %Y")}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            if active is not None:
                st.caption(f"{len(checks)} of {len(traps)} traps checked")
                if st.button("Resume checking", key=f"resume_{sid}", type="primary"):
                    go("visit", site_id=sid, visit_id=active["Visit ID"])
            else:
                if st.button("Start checking", key=f"open_{sid}", type="primary"):
                    vid = start_visit_now(data, sid, st.session_state.field_operator)
                    go("visit", site_id=sid, visit_id=vid)

elif page == "site":
    sid = st.session_state.site_id
    site_matches = data["Sites"][data["Sites"]["Site ID"] == sid]
    if site_matches.empty or site_matches.iloc[0]["Status"] != "Active":
        message_panel("warning", "This trap site is inactive.", ["Reactivate it in Administration before starting field work."])
        if st.button("Back to Trap sites"):
            go("sites")
        st.stop()
    s = site_matches.iloc[0]
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
    site_matches = data["Sites"][data["Sites"]["Site ID"] == sid]
    if site_matches.empty or site_matches.iloc[0]["Status"] != "Active":
        message_panel("warning", "This trap site is inactive.", ["Reactivate it in Administration before starting field work."])
        if st.button("Back to Trap sites"):
            go("sites")
        st.stop()
    vid = start_visit_now(data, sid, st.session_state.field_operator)
    go("visit", site_id=sid, visit_id=vid)

elif page == "visit":
    sid = st.session_state.site_id
    vid = st.session_state.visit_id
    visit_rows = data["Visits"][data["Visits"]["Visit ID"] == vid]
    if visit_rows.empty:
        message_panel("error", "This visit could not be found.", ["Return to Trap sites and start again."])
        if st.button("Back to Trap sites"):
            go("sites")
        st.stop()

    traps = data["Traps"][
        (data["Traps"]["Site ID"] == sid)
        & (data["Traps"]["Status"] == "Active")
    ].copy()
    checks = data["Checks"][data["Checks"]["Visit ID"] == vid]
    done = set(checks["Trap ID"].astype(str))

    header(site_name(data, sid), "Select the trap you are standing at.")
    saved = st.session_state.pop("saved_check", None)
    if saved:
        photo_count = int(saved.get("photo_count", 0))
        details = [f"{photo_count} photo{'s' if photo_count != 1 else ''} stored"] if photo_count else []
        message_panel("success", f"{saved['trap_id']} saved", details)

    filter_col, search_col = st.columns([1, 1.6])
    product_filter = filter_col.radio(
        "Trap type",
        ["All", "R1", "M1"],
        horizontal=True,
        key=f"visit_product_filter_{vid}",
    )
    search_text = search_col.text_input(
        "Find trap",
        placeholder="Trap ID or location",
        key=f"visit_trap_search_{vid}",
    ).strip().lower()

    if product_filter != "All":
        traps = traps[traps["Product"] == product_filter]
    if search_text:
        traps = traps[
            traps.apply(
                lambda row: search_text in str(row["Trap ID"]).lower()
                or search_text in trap_location_label(row).lower(),
                axis=1,
            )
        ]

    traps["_checked"] = traps["Trap ID"].astype(str).isin(done)
    traps["_route"] = pd.to_numeric(traps["Route Order"], errors="coerce")
    traps = traps.sort_values(["_checked", "Product", "_route", "Trap ID"])

    total_traps = len(data['Traps'][(data['Traps']['Site ID']==sid) & (data['Traps']['Status']=='Active')])
    checked_count = len(done)
    progress_value = min(1.0, checked_count / total_traps) if total_traps else 0.0
    st.progress(progress_value, text=f"{checked_count} of {total_traps} traps checked")
    all_checked = total_traps > 0 and checked_count >= total_traps
    if all_checked:
        message_panel("success", f"All {total_traps} traps checked", ["Finish the site check to record completion."])
    if traps.empty:
        helper("No traps match this filter.")
    else:
        for _, tr in traps.iterrows():
            trap_id = str(tr["Trap ID"])
            checked = trap_id in done
            render_visit_trap_card(tr, checked, vid, sid)

    st.markdown("### Site check actions")
    with st.container(border=True):
        if st.button(
            "Finish site check",
            type="primary",
            use_container_width=True,
            disabled=not all_checked,
            help="Check every active trap before completing the site visit." if not all_checked else None,
        ):
            idx = data["Visits"].index[data["Visits"]["Visit ID"] == vid][0]
            data["Visits"].at[idx, "End Time"] = dtstr()
            data["Visits"].at[idx, "Status"] = "Complete"
            save_data(data)
            set_flash("success", f"{site_name(data, sid)} site check completed", [f"All {total_traps} traps were checked."])
            st.session_state.completed_site_id = sid
            go("sites")
        if st.button("Pause and return to Trap sites", use_container_width=True):
            go("sites")

elif page == "check":
    sid, vid, trap_id = st.session_state.site_id, st.session_state.visit_id, st.session_state.trap_id
    tr = trap_row(data, trap_id)
    w = open_window(data, trap_id)

    if st.button("← Back to trap selector"):
        go("visit", site_id=sid, visit_id=vid)

    header(trap_id, f"{site_name(data, sid)} · {trap_location_label(tr)}")

    if w is None:
        message_panel("error", "This trap has no active test window.", ["Start it from the recorded deployment time, then continue this check."])
        if st.button("Start window and continue", type="primary"):
            try:
                repair_missing_window(data, trap_id)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        st.stop()

    st.caption(f"Current window · {w['Build Version']} · started {human_dt(w['Start Time'])}")
    finding = st.radio(
        "What did you find?",
        FINDINGS,
        index=None,
        key=f"finding_{trap_id}_{vid}",
    )
    if finding is None:
        st.caption("Choose one finding to continue.")
        st.stop()

    has_animal = finding == "Dead animal found"
    assessable = finding not in ["Trap missing", "Unable to check"]
    bag_id = ""
    species = ""
    rat_type = ""
    condition = ""
    bag_labelled = False
    photo_gate = {"ready": True, "expected_count": 0, "file_count": 0, "row_count": 0, "photos": []}

    if has_animal:
        bag_key = f"bag_id_{vid}_{trap_id}"
        pending_check_id = ensure_pending_check_id(vid, trap_id)
        if bag_key not in st.session_state:
            recovered_bag = recover_bag_id(DATA_ROOT, pending_check_id, vid, trap_id)
            st.session_state[bag_key] = recovered_bag or next_bag_id(data, sid)
        bag_id = st.session_state[bag_key]
        message_panel("warning", f"Bag ID: {bag_id}", ["Write this on the bag before moving on."])
        st.markdown("### Photos")
        st.caption("Choose the photos already taken from the camera roll.")
        photo_gate = render_check_photo_capture(vid, trap_id, sid, bag_id, str(w["Window ID"]))
        species = st.radio("Species", SPECIES, index=None, key=f"species_{trap_id}_{vid}")
        if species == "Rat":
            rat_type = st.radio("Rat type", RAT_TYPES, index=None, key=f"rat_type_{trap_id}_{vid}")
        condition = st.radio("Animal condition when found", ANIMAL_CONDITION, index=None, key=f"condition_{trap_id}_{vid}")
        bag_labelled = st.checkbox(f"Bag labelled {bag_id}", key=f"bagged_{trap_id}_{vid}")
    elif finding == "Trap fired, no animal":
        st.info("Camera review will determine whether this was a missed kill, false activation or non-target event.")
    elif not assessable:
        st.warning("This check will close the current window and no new window will start.")

    service_ready = False
    service_reason = ""
    if assessable:
        st.markdown("### Trap service")
        service_choice = st.radio(
            "Trap relured, reset and ready?",
            ["Yes", "No"],
            index=None,
            horizontal=True,
            key=f"service_ready_{trap_id}_{vid}",
        )
        service_ready = service_choice == "Yes"
        if service_choice == "No":
            service_reason = st.text_area(
                "Why is the trap not ready?",
                key=f"service_reason_{trap_id}_{vid}",
            ).strip()
    else:
        service_choice = "Not applicable"

    camera_assigned = bool(str(tr.get("Camera ID", "")).strip())
    camera = "No camera"
    covers = "Not applicable"
    adjusted = False
    camera_ready = True
    if camera_assigned and assessable:
        st.markdown("### Camera check")
        camera_choice = st.radio(
            "Camera working and covering the trap?",
            ["Yes", "No", "Could not assess"],
            index=None,
            key=f"camera_ready_{trap_id}_{vid}",
        )
        if camera_choice == "Yes":
            camera, covers, camera_ready = "Working", "Yes", True
        elif camera_choice == "No":
            camera = st.radio(
                "Camera issue",
                [x for x in CAMERA if x != "Working"],
                index=None,
                key=f"camera_issue_{trap_id}_{vid}",
            ) or ""
            covers = st.radio(
                "Camera still covers the trap?",
                ["Yes", "No", "Unsure"],
                index=None,
                key=f"covers_{trap_id}_{vid}",
            ) or ""
            adjusted = st.checkbox("Camera adjusted", key=f"adjusted_{trap_id}_{vid}")
            camera_ready = False
        elif camera_choice == "Could not assess":
            camera, covers, camera_ready = "Unsure", "Unsure", False
        else:
            camera_choice = None
            camera_ready = False
    else:
        camera_choice = "Not applicable"
        if not camera_assigned:
            st.caption("No camera assigned.")

    notes = st.text_area("Anything else to record?", height=72, key=f"notes_{trap_id}_{vid}")
    change_time = st.toggle("Change check time", value=False, key=f"change_time_{trap_id}_{vid}")
    if change_time:
        c1, c2 = st.columns(2)
        d = c1.date_input("Check date", value=now().date(), key=f"check_date_{trap_id}_{vid}")
        tm = c2.time_input("Check time", value=now().time(), key=f"check_time_{trap_id}_{vid}")
    else:
        d = tm = None

    photo_blocked = bool(has_animal and photo_gate.get("expected_count", 0) and not photo_gate.get("ready"))
    if has_animal and photo_gate.get("expected_count", 0):
        if photo_gate.get("manual_failure_count", 0):
            count = int(photo_gate["manual_failure_count"])
            st.caption(f"{count} photo{'s' if count != 1 else ''} could not upload")
        elif photo_gate.get("ready"):
            st.caption(f"{photo_gate['file_count']} photo{'s' if photo_gate['file_count'] != 1 else ''} saved")
        else:
            remaining = max(1, photo_gate.get("expected_count", 0) - photo_gate.get("file_count", 0))
            st.caption(f"Uploading {remaining} photo{'s' if remaining != 1 else ''}…")
    save_label = "Please wait" if photo_blocked else "Save check"
    if st.button(save_label, type="primary", key=f"save_check_{trap_id}_{vid}", use_container_width=True, disabled=photo_blocked):
        saving_feedback = st.empty()
        saving_feedback.info("Saving check… Do not tap again.")
        errors = []
        if has_animal and not species:
            errors.append("Choose the species.")
        if has_animal and species == "Rat" and not rat_type:
            errors.append("Choose the rat type.")
        if has_animal and not condition:
            errors.append("Choose the animal condition.")
        if has_animal and not bag_labelled:
            errors.append(f"Confirm that bag {bag_id} is labelled.")
        if assessable and service_choice is None:
            errors.append("Confirm whether the trap is relured, reset and ready.")
        if assessable and service_choice == "No" and not service_reason:
            errors.append("Record why the trap is not ready.")
        if camera_assigned and assessable and camera_choice is None:
            errors.append("Complete the camera check.")
        if camera_assigned and assessable and camera_choice == "No" and not camera:
            errors.append("Choose the camera issue.")
        if camera_assigned and assessable and camera_choice == "No" and not covers:
            errors.append("Record whether the camera covers the trap.")
        if errors:
            message_panel("error", "Complete these details before saving.", errors)
            st.stop()

        check_time = datetime.combine(d, tm).replace(microsecond=0) if change_time else now()
        if has_animal and photo_gate.get("expected_count", 0):
            photo_gate = {
                **photo_gate,
                **verify_pending_photo_transaction(DATA_ROOT, photo_gate["context"], MAX_SAVED_PHOTO_BYTES),
            }
            if not (
                photo_gate.get("ready")
                and photo_gate.get("expected_count") == photo_gate.get("file_count") == photo_gate.get("row_count")
            ):
                st.error("One or more selected photos are not safely stored yet.")
                st.stop()
        active = open_window(data, trap_id)
        if active is None:
            message_panel("error", "This trap has no active test window.", ["Start it from deployment time and retry."])
            if st.button("Start missing window", key=f"repair_on_save_{trap_id}_{vid}"):
                repair_missing_window(data, trap_id)
                st.rerun()
            st.stop()

        original_data = {name: frame.copy(deep=True) for name, frame in data.items()}
        staged = {name: frame.copy(deep=True) for name, frame in data.items()}
        old_id = close_window(staged, trap_id, check_time, finding, bag_id)
        will_start = bool(assessable and service_ready and camera_ready)
        new_id = start_window(staged, trap_id, check_time) if will_start else ""
        idxs = staged["Windows"].index[staged["Windows"]["Window ID"] == old_id].tolist()
        if idxs:
            staged["Windows"].at[idxs[0], "Species"] = species
            staged["Windows"].at[idxs[0], "Rat Type"] = rat_type

        expected_photo_count = int(photo_gate.get("expected_count", 0)) if has_animal else 0
        check_id = photo_gate.get("check_id") if expected_photo_count else make_id("CHK")
        trap_state = "Ready" if service_ready else ("Not ready" if assessable else "Not assessed")
        trap_function = "Ready after service" if service_ready else ("No" if assessable else "Unsure")
        row = [
            check_id, vid, trap_id, old_id, dtstr(check_time), finding, species, rat_type,
            condition, bag_id, "Yes" if bag_id else "No", "Yes" if bag_labelled else "No",
            "", "Yes" if service_ready else "No", "Yes" if assessable else "No",
            "Yes" if service_ready else "No", "Yes" if service_ready else "No",
            trap_function, "", camera, covers, "Yes" if adjusted else "No", new_id,
            (service_reason + (" · " if service_reason and notes else "") + notes).strip(),
        ]
        staged["Checks"] = pd.concat([staged["Checks"], pd.DataFrame([row], columns=SHEETS["Checks"])], ignore_index=True)

        if assessable and camera_assigned:
            priority = "High" if finding == "Trap fired, no animal" else "Normal"
            add_followup(staged, "Camera review", sid, trap_id, vid, old_id, bag_id, finding,
                         "Confirm target interaction, activation, kill and video evidence", priority)
        if has_animal:
            add_followup(staged, "Necropsy review", sid, trap_id, vid, old_id, bag_id,
                         "Dead animal collected",
                         "Add necropsy result, weight range, measurements and final humane-kill conclusion", "Normal")
        if assessable and not service_ready:
            add_followup(staged, "Trap not ready", sid, trap_id, vid, old_id, bag_id,
                         service_reason, "Restore the trap to service and record the outcome", "High")
        if camera_issue_required(camera_assigned, camera, covers):
            add_followup(staged, "Camera issue", sid, trap_id, vid, old_id, bag_id,
                         "Camera issue", "Resolve camera condition and record the evidence gap", "High")

        refresh_review_status(staged, old_id)
        saved_photo_files = []
        final_copies = []
        rollback_copy = DATA_ROOT / f".{DATA_FILE.name}.{uuid.uuid4().hex}.photo-rollback.xlsx"
        workbook_save_attempted = False
        workbook_restored = False
        files_restored = False
        rollback_checksum = ""
        try:
            if expected_photo_count:
                # Verify again at the final commit boundary using the durable pending manifest.
                photo_gate = {
                    **photo_gate,
                    **verify_pending_photo_transaction(DATA_ROOT, photo_gate["context"], MAX_SAVED_PHOTO_BYTES),
                }
                if not (
                    photo_gate.get("ready")
                    and photo_gate.get("expected_count") == photo_gate.get("file_count") == photo_gate.get("row_count")
                ):
                    raise RuntimeError(
                        f"Photo integrity check failed: expected {photo_gate.get('expected_count', 0)}, "
                        f"files {photo_gate.get('file_count', 0)}, rows {photo_gate.get('row_count', 0)}."
                    )

                final_plan = build_finalisation_plan(DATA_ROOT, photo_gate["context"], MAX_SAVED_PHOTO_BYTES)
                final_copies = apply_final_copies(final_plan)
                prepared_rows = [
                    [row.get(column, "") for column in SHEETS["Photos"]]
                    for row in final_plan.get("rows", [])
                ]
                saved_photo_files = [destination for _, destination, _ in final_copies]
                if len(prepared_rows) != expected_photo_count or len(saved_photo_files) != expected_photo_count:
                    raise RuntimeError(
                        f"Photo finalisation mismatch: expected {expected_photo_count}, rows {len(prepared_rows)}, files {len(saved_photo_files)}."
                    )
                if any(not path.exists() or path.stat().st_size <= 0 for path in saved_photo_files):
                    raise RuntimeError("One or more selected photo files were missing before final save.")
                staged["Photos"] = pd.concat(
                    [staged["Photos"], pd.DataFrame(prepared_rows, columns=SHEETS["Photos"])],
                    ignore_index=True,
                )

            committed_rows = staged["Photos"][
                staged["Photos"]["Check ID"].astype(str) == str(check_id)
            ]
            if len(committed_rows) != expected_photo_count or committed_rows["Photo ID"].astype(str).nunique() != expected_photo_count:
                raise RuntimeError(
                    f"Photo record mismatch: expected {expected_photo_count}, recorded {len(committed_rows)}, "
                    f"distinct {committed_rows['Photo ID'].astype(str).nunique()}."
                )

            if DATA_FILE.exists():
                shutil.copy2(DATA_FILE, rollback_copy)
                rollback_checksum = hashlib.sha256(rollback_copy.read_bytes()).hexdigest()
            workbook_save_attempted = True
            save_data(staged)

            reloaded = load_data()
            persisted_check = reloaded["Checks"][reloaded["Checks"]["Check ID"].astype(str) == str(check_id)]
            persisted_photos = reloaded["Photos"][reloaded["Photos"]["Check ID"].astype(str) == str(check_id)]
            persisted_followups = reloaded["Followups"][reloaded["Followups"]["Visit ID"].astype(str) == str(vid)]
            if len(persisted_check) != 1:
                raise RuntimeError("The saved workbook did not contain exactly one completed check.")
            if len(persisted_photos) != expected_photo_count or persisted_photos["Photo ID"].astype(str).nunique() != expected_photo_count:
                raise RuntimeError("The saved workbook did not contain the complete verified photo set.")
            for _, persisted_photo in persisted_photos.iterrows():
                rel = _safe_relative_photo_path(persisted_photo["File Path"])
                path = DATA_ROOT / rel if rel else None
                if path is None or not path.exists() or path.stat().st_size <= 0:
                    raise RuntimeError("A saved Photos row did not point to a valid stored file.")

            log_photo_event(
                DATA_ROOT, "check_commit_verified", check_id=check_id, trap_id=trap_id,
                expected_count=expected_photo_count, photo_row_count=len(persisted_photos),
                followup_count=len(persisted_followups),
            )
            for name in data:
                data[name] = reloaded[name]

        except Exception as exc:
            rollback_errors = []
            if workbook_save_attempted and rollback_copy.exists():
                try:
                    restore_temp = DATA_ROOT / f".{DATA_FILE.name}.{uuid.uuid4().hex}.restore.xlsx"
                    shutil.copy2(rollback_copy, restore_temp)
                    os.replace(restore_temp, DATA_FILE)
                    if rollback_checksum and hashlib.sha256(DATA_FILE.read_bytes()).hexdigest() != rollback_checksum:
                        raise RuntimeError("restored workbook did not match the pre-save workbook")
                    workbook_restored = True
                except Exception as rollback_exc:
                    rollback_errors.append(f"workbook rollback: {rollback_exc}")
            else:
                workbook_restored = True

            if final_copies:
                try:
                    rollback_final_copies(final_copies)
                    files_restored = True
                except Exception as rollback_exc:
                    rollback_errors.append(f"photo rollback: {rollback_exc}")
            else:
                files_restored = True

            for name in data:
                data[name] = original_data[name]
            log_photo_event(
                DATA_ROOT, "check_commit_failed", check_id=check_id, trap_id=trap_id,
                error=str(exc)[:500], workbook_restored=workbook_restored, files_restored=files_restored,
                rollback_errors=rollback_errors,
            )
            rollback_copy.unlink(missing_ok=True)
            if rollback_errors or not (workbook_restored and files_restored):
                st.error("Save failed and automatic rollback could not be confirmed. Do not continue this check; contact the trial lead.")
            else:
                st.error("Save failed. No check, follow-up or photo record was committed. Your selected photos remain available to retry.")
            st.stop()
        finally:
            rollback_copy.unlink(missing_ok=True)

        if expected_photo_count:
            delete_transaction(DATA_ROOT, check_id)

        for key in [
            f"bag_id_{vid}_{trap_id}",
            pending_check_id_key(vid, trap_id),
            photo_component_event_key(vid, trap_id),
        ]:
            st.session_state.pop(key, None)
        st.session_state.saved_check = {
            "trap_id": trap_id,
            "photo_count": len(saved_photo_files),
        }
        go("visit", site_id=sid, visit_id=vid)

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
                render_compact_card_content(
                    title=trap_id,
                    right_label=site_name(data, tr["Site ID"]),
                    main_line=f"{trap_location_label(tr)} · Trap {tr['Route Order']}",
                    meta_line=(
                        f"{tr['Build Version']} · "
                        f"{len(kills)} kill{'s' if len(kills) != 1 else ''} · "
                        f"{len(trap_checks)} check{'s' if len(trap_checks) != 1 else ''} · "
                        f"Last kill: {last_kill}"
                    ),
                )

                if st.button(
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
                    bag_text = f"Bag {item_row['Bag ID']} · " if str(item_row.get("Bag ID", "")).strip() else ""
                    reason_text = item_row["Reason"] or "—"
                    st.markdown(
                        '<div class="shared-card-copy">'
                        f'<div class="shared-card-heading"><strong>{html.escape(str(item_row["Trap ID"]))}</strong><span class="shared-card-label">{html.escape(str(item_row["Follow-up Type"]))}</span></div>'
                        f'<div class="shared-card-meta">{html.escape(site_name(data,item_row["Site ID"]))} · {html.escape(str(item_row["Priority"]))}</div>'
                        f'<div class="shared-card-meta">{html.escape(bag_text + str(reason_text))} · Created {html.escape(human_dt(item_row["Created Time"]))}</div>'
                        '</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("Review",key=f"followup_review_{row_fid}",use_container_width=True):
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
            header(item["Follow-up Type"], f"{item['Trap ID']} · {site_name(data,item['Site ID'])}" + (f" · Bag {item['Bag ID']}" if str(item.get("Bag ID", "")).strip() else ""))

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


elif page == "trap_edit":
    trap_id = st.session_state.get("trap_id", "")
    existing = trap_row(data, trap_id)
    if existing is None:
        message_panel("error", "This trap could not be found.")
        if st.button("Back to Trial setup"):
            go("setup")
        st.stop()

    if st.button("← Back to Trial setup"):
        go("setup")
    header(f"Edit {trap_id}", f"{site_name(data, existing['Site ID'])} · {trap_location_label(existing)}")

    with st.form(f"trap_edit_page_{trap_id}"):
        location = st.text_input("Location description", value=trap_location_label(existing))
        camera = st.text_input("Camera ID", value=existing["Camera ID"])
        order = st.number_input(
            "Route reference",
            min_value=1,
            step=1,
            value=int(float(existing["Route Order"])) if str(existing["Route Order"]).strip() else 1,
        )
        status = st.radio(
            "Status",
            ["Active", "Inactive"],
            index=0 if existing["Status"] == "Active" else 1,
            horizontal=True,
        )
        notes = st.text_area("Notes", value=existing["Notes"])
        save_edit = st.form_submit_button("Save changes", type="primary")
    if save_edit:
        idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
        data["Traps"].at[idx, "Location"] = location.strip()
        data["Traps"].at[idx, "Camera ID"] = camera.strip()
        data["Traps"].at[idx, "Route Order"] = str(order)
        data["Traps"].at[idx, "Status"] = status
        data["Traps"].at[idx, "Notes"] = notes
        save_data(data)
        set_flash("success", f"{trap_id} updated.")
        go("setup")

    st.divider()
    show_move = st.toggle("Move trap", key=f"show_move_{trap_id}")
    if show_move:
        active_destinations = data["Sites"][
            (data["Sites"]["Status"] == "Active")
            & (data["Sites"]["Site ID"] != existing["Site ID"])
        ]["Site ID"].tolist()
        if active_destinations:
            destination = st.selectbox("Destination site", active_destinations, format_func=lambda x: site_name(data, x))
            move_location = st.text_input("Location at destination", value="")
            move_order = st.number_input("Route reference at destination", min_value=1, step=1, value=int(float(existing["Route Order"])) if str(existing["Route Order"]).strip() else 1)
            move_camera = st.text_input("Camera ID at destination", value=existing["Camera ID"])
            move_reason = st.text_area("Reason for move")
            move_date = st.date_input("Effective date", value=now().date())
            move_time = st.time_input("Effective time", value=now().time())
            confirm_move = st.checkbox("Close the current window and start a new window at the destination")
            if st.button("Move trap", type="primary", disabled=not confirm_move):
                try:
                    move_trap(
                        data, trap_id, destination,
                        datetime.combine(move_date, move_time).replace(microsecond=0),
                        move_reason.strip(), move_order, move_location.strip(), move_camera.strip()
                    )
                    set_flash("success", f"{trap_id} moved.", [f"New site: {site_name(data, destination)}."])
                    go("setup")
                except Exception as exc:
                    st.error(str(exc))
        else:
            st.caption("No other active sites are available.")

    with st.expander("Change build"):
        available_builds = data["Builds"][data["Builds"]["Build Status"] != "Withdrawn"].copy()
        available_builds["Label"] = available_builds["Product"].astype(str) + " · " + available_builds["Build Version"].astype(str)
        current_label = f"{existing['Product']} · {existing['Build Version']}"
        options = [x for x in available_builds["Label"].tolist() if x != current_label]
        if options:
            new_label = st.selectbox("New build", options)
            build_reason = st.text_area("Reason for build change")
            build_date = st.date_input("Effective date", value=now().date(), key=f"dedicated_build_date_{trap_id}")
            build_time = st.time_input("Effective time", value=now().time(), key=f"dedicated_build_time_{trap_id}")
            confirm_build = st.checkbox("Close the current window and start a new window on this build")
            if st.button("Change build", type="primary", disabled=not confirm_build):
                selected = available_builds[available_builds["Label"] == new_label].iloc[0]
                try:
                    change_trap_build(
                        data, trap_id, str(selected["Product"]), str(selected["Build Version"]),
                        datetime.combine(build_date, build_time).replace(microsecond=0),
                        build_reason.strip(),
                    )
                    set_flash("success", f"{trap_id} build changed.", [f"New build: {new_label}."])
                    go("setup")
                except Exception as exc:
                    st.error(str(exc))
        else:
            st.caption("No other available builds.")

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
                        st.markdown('<span class="setup-trap-card-marker" aria-hidden="true"></span>', unsafe_allow_html=True)
                        camera_text = tr["Camera ID"] or "No camera"
                        st.markdown(
                            '<div class="shared-card-copy">'
                            f'<div class="shared-card-heading"><strong>{html.escape(str(trap_id))}</strong><span class="shared-card-label">{html.escape(str(tr["Status"]))}</span></div>'
                            f'<div class="shared-card-main">{html.escape(trap_location_label(tr))} · {html.escape(site_name(data, tr["Site ID"]))}</div>'
                            f'<div class="shared-card-meta">{html.escape(str(tr["Product"]))} · Build {html.escape(str(tr["Build Version"] or "—"))} · {html.escape(str(camera_text))} · Route {html.escape(str(tr["Route Order"] or "—"))}</div>'
                            '</div>',
                            unsafe_allow_html=True,
                        )
                        if st.button("Edit", key=f"setup_edit_trap_{trap_id}"):
                            go("trap_edit", trap_id=trap_id)
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
                assignable_builds=data["Builds"][data["Builds"]["Build Status"]!="Withdrawn"].copy()
                assignable_builds["Build label"]=assignable_builds["Product"].astype(str)+" · "+assignable_builds["Build Version"].astype(str)
                build_options=assignable_builds["Build label"].tolist()
                existing_build_label=(f"{existing['Product']} · {existing['Build Version']}" if existing is not None else "")
                with st.form("trap_setup_panel"):
                    trap_id=st.text_input("Trap ID",value=existing["Trap ID"] if existing is not None else "",disabled=mode=="edit",help="Permanent physical trap ID. Do not include the site code.")
                    build_label=st.selectbox("Build",build_options,index=(build_options.index(existing_build_label) if existing_build_label in build_options else 0),disabled=mode=="edit",help="Use Change build for an existing trap.")
                    build_row=assignable_builds[assignable_builds["Build label"]==build_label].iloc[0]
                    product=str(build_row["Product"]); build=str(build_row["Build Version"])
                    st.caption(f"Trap type: {product}")
                    active_site_options=data["Sites"][data["Sites"]["Status"]=="Active"]["Site ID"].tolist()
                    site_options=active_site_options.copy()
                    if existing is not None and existing["Site ID"] not in site_options:
                        site_options=[existing["Site ID"]]+site_options
                    site=st.selectbox("Site",site_options,index=(site_options.index(existing["Site ID"]) if existing is not None and existing["Site ID"] in site_options else 0),format_func=lambda x:site_name(data,x),help="Use Move trap for an existing trap.",disabled=mode=="edit")
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
                            old_site=data["Traps"].at[idx,"Site ID"]
                            if old_site!=site:
                                st.error("Use Move trap to change sites. Direct site changes are blocked so trial history is not rewritten.")
                            elif old_build!=build and open_window(data,trap_id) is not None:
                                st.error("Close the active test window before changing this trap's build.")
                            else:
                                data["Traps"].loc[idx,SHEETS["Traps"]]=row
                                save_data(data)
                                set_flash("success", f"{trap_id} updated.", ["Trap setup changes were saved."])
                                st.session_state.pop("setup_mode",None); st.session_state.pop("setup_trap",None); st.rerun()
                        else:
                            deployment_time=datetime.combine(dep_date,dep_time)
                            data["Traps"]=pd.concat([data["Traps"],pd.DataFrame([row],columns=SHEETS["Traps"])],ignore_index=True)
                            if status=="Active":
                                start_window(data,trap_id,deployment_time)
                            save_data(data)
                            set_flash("success", f"{trap_id} added.", [f"Assigned to {site_name(data,site)}.", "An active test window was started." if status=="Active" else "The trap was added as inactive."])
                            st.session_state.pop("setup_mode",None); st.rerun()
                if mode=="edit":
                    st.divider()
                    show_inline_move = st.toggle("Move trap", key=f"show_inline_move_{trap_id}")
                    if show_inline_move:
                        active_destinations = data["Sites"][
                            (data["Sites"]["Status"] == "Active")
                            & (data["Sites"]["Site ID"] != existing["Site ID"])
                        ]["Site ID"].tolist()
                        if not active_destinations:
                            st.caption("No other active sites are available.")
                        else:
                            destination = st.selectbox(
                                "Destination site",
                                active_destinations,
                                format_func=lambda x: site_name(data, x),
                                key=f"move_destination_{trap_id}",
                            )
                            move_order = st.number_input(
                                "Route reference",
                                min_value=1,
                                step=1,
                                value=int(float(existing["Route Order"])) if str(existing["Route Order"]).strip() else 1,
                                key=f"move_order_{trap_id}",
                            )
                            move_location = st.text_input(
                                "Location at destination",
                                value="",
                                key=f"move_location_{trap_id}",
                            )
                            move_camera = st.text_input(
                                "Camera ID at destination",
                                value=existing["Camera ID"],
                                key=f"move_camera_{trap_id}",
                            )
                            move_date = st.date_input("Effective date", value=now().date(), key=f"move_date_{trap_id}")
                            move_time = st.time_input("Effective time", value=now().time(), key=f"move_time_{trap_id}")
                            move_reason = st.text_area("Reason for move", key=f"move_reason_{trap_id}")
                            confirm_move = st.checkbox(
                                f"Move {trap_id} from {site_name(data, existing['Site ID'])} and start a new window",
                                key=f"confirm_move_{trap_id}",
                            )
                            if st.button("Move trap", type="primary", key=f"move_trap_{trap_id}", disabled=not confirm_move):
                                if not move_reason.strip():
                                    st.error("Enter a reason for the move.")
                                elif not move_location.strip():
                                    st.error("Enter the trap location at the destination.")
                                else:
                                    try:
                                        effective = datetime.combine(move_date, move_time).replace(microsecond=0)
                                        move_trap(data, trap_id, destination, effective, move_reason.strip(), move_order, move_location.strip(), move_camera.strip())
                                        set_flash("success", f"{trap_id} moved.", [f"New site: {site_name(data, destination)}.", "Historical windows remain on the previous site."])
                                        st.session_state.pop("setup_mode", None)
                                        st.session_state.pop("setup_trap", None)
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(str(exc))

                    with st.expander("Change build"):
                        available_builds = data["Builds"][data["Builds"]["Build Status"] != "Withdrawn"].copy()
                        available_builds["Label"] = available_builds["Product"].astype(str) + " · " + available_builds["Build Version"].astype(str)
                        current_label = f"{existing['Product']} · {existing['Build Version']}"
                        build_choices = [x for x in available_builds["Label"].tolist() if x != current_label]
                        if not build_choices:
                            st.caption("No other available builds.")
                        else:
                            new_label = st.selectbox("New build", build_choices, key=f"change_build_{trap_id}")
                            build_date = st.date_input("Effective date", value=now().date(), key=f"build_change_date_{trap_id}")
                            build_time = st.time_input("Effective time", value=now().time(), key=f"build_change_time_{trap_id}")
                            build_reason = st.text_area("Reason for build change", key=f"build_change_reason_{trap_id}")
                            confirm_build = st.checkbox(
                                "Close the current window and start a new one on this build",
                                key=f"confirm_build_change_{trap_id}",
                            )
                            if st.button("Change build", type="primary", key=f"commit_build_change_{trap_id}", disabled=not confirm_build):
                                if not build_reason.strip():
                                    st.error("Enter a reason for the build change.")
                                else:
                                    selected = available_builds[available_builds["Label"] == new_label].iloc[0]
                                    effective = datetime.combine(build_date, build_time).replace(microsecond=0)
                                    try:
                                        change_trap_build(data, trap_id, str(selected["Product"]), str(selected["Build Version"]), effective, build_reason.strip())
                                        set_flash("success", f"{trap_id} build changed.", [f"New build: {new_label}.", "Previous windows retain the previous build."])
                                        st.session_state.pop("setup_mode", None)
                                        st.session_state.pop("setup_trap", None)
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(str(exc))

                    st.divider()
                    if trap_can_be_deleted(data, trap_id):
                        st.caption("This trap has no field history and can be deleted.")
                        confirm_delete=st.checkbox(f"Delete {trap_id}", key=f"confirm_delete_{trap_id}")
                        if st.button("Delete unused trap", key=f"delete_unused_{trap_id}", disabled=not confirm_delete):
                            delete_unused_trap(data,trap_id)
                            set_flash("success", f"{trap_id} deleted.", ["The unused trap and its untouched test window were removed."])
                            st.session_state.pop("setup_mode",None); st.session_state.pop("setup_trap",None); st.rerun()
                    else:
                        st.caption("This trap has trial history, so it cannot be deleted. Set its status to Inactive instead.")
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
                    coverage_text = (
                        "Mobile coverage confirmed"
                        if site_row.get("Mobile Coverage Confirmed", "") == "Yes"
                        else "Mobile coverage not confirmed"
                    )
                    render_compact_card_content(
                        title=str(site_row["Site Name"]),
                        right_label=str(site_row["Status"]),
                        main_line=f"{sid} · {trap_count} active trap{'s' if trap_count != 1 else ''}",
                        meta_line=f"Every {site_row['Visit Interval Days']} days · {coverage_text}",
                    )
                    if st.button("Edit", key=f"setup_edit_site_{sid}"):
                        st.session_state.setup_site=sid; st.session_state.site_mode="edit"; st.rerun()
        if panel is not None:
            with panel:
                ex=data["Sites"][data["Sites"]["Site ID"]==st.session_state.get("setup_site","")].iloc[0] if mode=="edit" else None
                st.subheader("Edit site" if mode=="edit" else "Add site")
                with st.form("site_setup_panel"):
                    sid=st.text_input("Site ID",value=ex["Site ID"] if ex is not None else "",disabled=mode=="edit")
                    name=st.text_input("Site name",value=ex["Site Name"] if ex is not None else "")
                    interval=3
                    st.number_input("Visit interval days",min_value=3,max_value=3,step=1,value=3,disabled=True,help="Three days is the planned cadence, not a validity limit. Earlier or later checks remain valid and use their actual timestamps.")
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
                    active_traps_at_site = len(data["Traps"][
                        (data["Traps"]["Site ID"] == sid)
                        & (data["Traps"]["Status"] == "Active")
                    ])
                    if mode=="edit" and status=="Inactive" and active_traps_at_site:
                        st.error(f"Move or deactivate the {active_traps_at_site} active trap{'s' if active_traps_at_site != 1 else ''} at this site before making it inactive.")
                        st.stop()
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
                product_code = str(build_row["Product"])
                version = str(build_row["Build Version"])
                build_identity = f"{product_code}::{version}"
                active_traps = len(data["Traps"][
                    (data["Traps"]["Product"].astype(str) == product_code)
                    & (data["Traps"]["Build Version"].astype(str) == version)
                    & (data["Traps"]["Status"] == "Active")
                ])
                with app_card():
                    first_active = parse_dt(build_row["First Active Date"])
                    first_active_text = first_active.strftime("%d %b %Y") if first_active else "—"
                    render_compact_card_content(
                        title=f"{product_code} Build {version}",
                        right_label=str(build_row["Build Status"]),
                        main_line=f"{active_traps} active trap{'s' if active_traps != 1 else ''}",
                        meta_line=f"First active {first_active_text} · {build_row['Notes'] or 'No notes'}",
                    )
                    if st.button("Edit", key=f"setup_edit_build_{product_code}_{version}"):
                        st.session_state.setup_build=build_identity
                        st.session_state.build_mode="edit"
                        st.rerun()
        if panel is not None:
            with panel:
                if mode=="edit":
                    selected_build_identity=st.session_state.get("setup_build","")
                    selected_product, selected_version = selected_build_identity.split("::", 1)
                    matching_builds=data["Builds"][
                        (data["Builds"]["Product"].astype(str)==selected_product)
                        & (data["Builds"]["Build Version"].astype(str)==selected_version)
                    ]
                    ex=matching_builds.iloc[0]
                else:
                    ex=None
                st.subheader("Edit build" if mode=="edit" else "Add build")
                with st.form(f"build_setup_panel_{mode}_{st.session_state.get('setup_build', 'new')}"):
                    product=st.selectbox("Trap type",["R1","M1"],index=0 if ex is None or ex["Product"]=="R1" else 1)
                    version=st.text_input("Build version",value=ex["Build Version"] if ex is not None else "",disabled=mode=="edit")
                    status=st.selectbox("Build status",["Current","Trial comparison","Superseded","Withdrawn"],index=(["Current","Trial comparison","Superseded","Withdrawn"].index(ex["Build Status"]) if ex is not None and ex["Build Status"] in ["Current","Trial comparison","Superseded","Withdrawn"] else 0))
                    first=parse_dt(ex["First Active Date"]) if ex is not None else now(); first_date=st.date_input("First active date",value=first.date() if first else now().date())
                    notes=st.text_area("Notes",value=ex["Notes"] if ex is not None else "")
                    save=st.form_submit_button("Save build changes" if mode=="edit" else "Add build",type="primary")
                if save:
                    version=version.strip()
                    duplicate=((data["Builds"]["Product"].astype(str)==str(product)) & (data["Builds"]["Build Version"].astype(str).str.casefold()==version.casefold()))
                    if not version:
                        st.error("Build version is required.")
                    elif mode=="add" and duplicate.any():
                        st.error("That build version already exists for this trap type.")
                    else:
                        row=[product,version,status,first_date.strftime("%Y-%m-%d"),notes]
                        if mode=="edit":
                            idx=data["Builds"].index[(data["Builds"]["Product"]==ex["Product"]) & (data["Builds"]["Build Version"]==ex["Build Version"])][0]
                            data["Builds"].loc[idx,SHEETS["Builds"]]=row
                        else:
                            data["Builds"]=pd.concat([data["Builds"],pd.DataFrame([row],columns=SHEETS["Builds"])],ignore_index=True)
                        save_data(data)
                        set_flash("success", f"{version} saved.", ["It is now available when adding a trap unless marked Withdrawn."])
                        st.session_state.pop("build_mode",None); st.session_state.pop("setup_build",None); st.rerun()
                if mode=="edit":
                    used_by_traps = (
                        (data["Traps"]["Product"].astype(str) == str(ex["Product"]))
                        & (data["Traps"]["Build Version"].astype(str) == str(ex["Build Version"]))
                    ).any()
                    used_by_windows = (
                        (data["Windows"]["Product"].astype(str) == str(ex["Product"]))
                        & (data["Windows"]["Build Version"].astype(str) == str(ex["Build Version"]))
                    ).any()
                    if not used_by_traps and not used_by_windows:
                        st.divider()
                        st.caption("This build is unused and can be removed.")
                        build_remove_reason = st.text_area(
                            "Removal reason",
                            key=f"remove_build_reason_{selected_product}_{selected_version}",
                        )
                        confirm_build_remove = st.checkbox(
                            f"Remove {selected_product} · {selected_version}",
                            key=f"confirm_remove_build_{selected_product}_{selected_version}",
                        )
                        if st.button(
                            "Remove unused build",
                            disabled=not confirm_build_remove,
                            key=f"remove_unused_build_{selected_product}_{selected_version}",
                        ):
                            try:
                                remove_unused_build(data, selected_product, selected_version, build_remove_reason)
                                set_flash("success", f"{selected_product} · {selected_version} removed.")
                                st.session_state.pop("build_mode", None)
                                st.session_state.pop("setup_build", None)
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))
                if st.button("Cancel",key="cancel_build_panel"): st.session_state.pop("build_mode",None); st.session_state.pop("setup_build",None); st.rerun()
elif page == "data_management":
    header("Data & records", "Correct records, review trial periods and changes, or export the workbook.")
    active_data_section = st.radio(
        "Data section",
        ["Corrections", "Trial history", "Audit log", "Export and backup"],
        horizontal=True,
        key="data_management_section",
        label_visibility="collapsed",
    )

    if active_data_section == "Corrections":
        helper("Use corrections only for known data-entry mistakes. Every change requires a reason and is retained in the audit log.")
        st.markdown("#### What you are recording")
        st.write("The corrected value and why the original entry was wrong.")
        st.markdown("#### What the app will update")
        st.write("The linked record, any affected Performance figures, and a permanent audit-log entry.")
        record_type = st.selectbox("Record type", ["Camera evidence", "Necropsy evidence", "Field check", "Follow-up task"])
        search_text = st.text_input("Find by trap, window, bag or check ID").strip().lower()

        if record_type == "Follow-up task":
            candidates = data["Followups"].copy()
            if search_text:
                mask = candidates[["Follow-up ID", "Trap ID", "Bag ID", "Window ID", "Reason"]].astype(str).apply(
                    lambda col: col.str.lower().str.contains(search_text, na=False)
                ).any(axis=1)
                candidates = candidates[mask]
            options = candidates["Follow-up ID"].astype(str).tolist()
            selected_id = st.selectbox(
                "Select follow-up task",
                options,
                format_func=lambda fid: (
                    lambda r: f"{r['Follow-up Type']} · {r['Trap ID']} · "
                    + (f"Bag {r['Bag ID']} · " if str(r.get('Bag ID', '')).strip() else "")
                    + f"{r['Status']} · {fid}"
                )(candidates[candidates["Follow-up ID"].astype(str) == str(fid)].iloc[0]),
            ) if options else None
            if selected_id:
                row = candidates[candidates["Follow-up ID"].astype(str) == str(selected_id)].iloc[0]
                workflow_context([
                    ("Task", row["Follow-up Type"]),
                    ("Trap", row["Trap ID"]),
                    ("Site", site_name(data, row["Site ID"])),
                    ("Bag ID", row["Bag ID"]),
                    ("Window", row["Window ID"]),
                    ("Reason", row["Reason"]),
                    ("Status", row["Status"]),
                ])
                st.warning("Use this only for an invalid or bundled dummy task. The linked check and test window will remain.")
                remove_reason = st.text_area("Reason for removal", key=f"remove_followup_reason_{selected_id}")
                confirm_remove = st.checkbox(
                    f"Remove follow-up {selected_id}",
                    key=f"confirm_remove_followup_{selected_id}",
                )
                if st.button(
                    "Remove invalid follow-up",
                    type="primary",
                    disabled=not confirm_remove,
                    key=f"remove_followup_{selected_id}",
                ):
                    try:
                        removed = remove_followup_task(data, selected_id, remove_reason)
                        set_flash(
                            "success",
                            "Follow-up removed.",
                            [
                                f"{removed['Follow-up Type']} for {removed['Trap ID']} was removed.",
                                "The linked check and test window were preserved.",
                                "The removal is recorded in the audit log.",
                            ],
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        elif record_type in ["Camera evidence", "Necropsy evidence"]:
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

    if active_data_section == "Trial history":
        helper("Trial history shows each period between a trap being set or relured and its next field check.")
        st.write("Use it to trace how a field finding, camera review and final performance result link together.")
        if st.button("Open trial history", type="primary", key="open_trial_history"):
            go("windows")

    if active_data_section == "Audit log":
        if data["Audit Log"].empty:
            st.info("No corrections have been recorded yet.")
        else:
            audit_view = data["Audit Log"].copy().iloc[::-1]
            st.dataframe(audit_view, use_container_width=True, hide_index=True)

    if active_data_section == "Export and backup":
        sheet = st.selectbox("Inspect data table", list(SHEETS), key="data_management_sheet")
        st.dataframe(data[sheet], use_container_width=True, hide_index=True)
        st.caption("Export is read-only. Opening this page does not change trial data.")
        with open(DATA_FILE, "rb") as f:
            st.download_button("Download complete Excel backup", f, file_name=DATA_FILE.name, type="primary")

        if os.getenv("R1M1_ENABLE_RECOVERY_TOOLS", "").strip() == "1":
            with st.expander("Emergency recovery tools"):
                backups = available_backups()
                if backups:
                    backup_options = [str(path) for path in backups]
                    selected_backup = st.selectbox(
                        "Backup",
                        backup_options,
                        format_func=lambda value: f"{Path(value).name} · {workbook_summary(Path(value))}",
                        key="emergency_recovery_backup",
                    )
                    confirm_restore = st.checkbox(
                        "Replace the current workbook with this backup",
                        key="confirm_emergency_restore",
                    )
                    if st.button("Restore selected backup", disabled=not confirm_restore):
                        try:
                            restore_backup(Path(selected_backup))
                            set_flash("success", "Backup restored.")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))


# Navigation scroll reset runs last so the destination DOM is already mounted.
scroll_to_top_once()
