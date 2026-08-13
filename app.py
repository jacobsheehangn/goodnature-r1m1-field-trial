from __future__ import annotations

import uuid
import hashlib
import hmac
import logging
import os
import shutil
import re
from io import BytesIO
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
from zoneinfo import ZoneInfo

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

_logger = logging.getLogger(__name__)

APP_TITLE = "R1/M1 Field Trial — v8.7.6.7 Photo Integrity Corrections"
APP_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("R1M1_DATA_DIR", str(APP_DIR))).expanduser().resolve()
DATA_FILE = DATA_ROOT / "field_trial_data_v8_6_5.xlsx"
DEMO_SEED_DATA_FILE = APP_DIR / "field_trial_data_v8_6_5.xlsx"
CLEAN_SEED_DATA_FILE = APP_DIR / "field_trial_data_clean_seed.xlsx"
SEED_MODE = os.environ.get("R1M1_SEED_MODE", "clean").strip().lower()
# Was "demo" by default - R1_M1_Agreed_Release_Sequence_Updated.md's Data
# administration section calls for removing bundled demo records safely.
# "demo" is still available as an explicit opt-in (this session's own local
# testing has used it throughout), just no longer what a fresh deploy gets
# without asking for it. "clean" ships the same site/trap/build scaffold
# with zero fabricated Checks/Windows/Followups/Audit Log activity - no
# fake kills or results to accidentally count toward real trial numbers.
SEED_DATA_FILE = DEMO_SEED_DATA_FILE if SEED_MODE == "demo" else CLEAN_SEED_DATA_FILE
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
    "Checks": ["Check ID", "Visit ID", "Trap ID", "Window Closed", "Check Time", "Finding", "Species", "Rat Type", "Animal Condition When Found", "Bag ID", "Animal Cleared", "Animal Bagged", "Lure Condition", "Relured", "Reset Required", "Trap Reset", "Trap Ready After Check", "Trap Function", "Site Condition", "Camera Condition", "Camera Covers Trap", "Camera Adjusted", "New Window", "Notes", "Excluded", "Exclusion Reason"],
    "Windows": ["Window ID", "Trap ID", "Product", "Build Version", "Site ID", "Camera Assigned", "Start Time", "End Time", "Status", "End Reason", "Finding At Close", "Species", "Rat Type", "Evidence Usable", "Target Present", "Interaction Level", "Entered Strike Area", "Trap Activated", "Activation Evidence", "Kill Confirmed", "Outcome", "First Target Time", "First Interaction Time", "Trigger Time", "Kill Time", "Time To First Target Hr", "Time To First Interaction Hr", "Interaction To Trigger Min", "Interaction To Kill Min", "Time To Kill Hr", "Video Assessment", "Video Link", "Necropsy Status", "Necropsy Assessment", "Animal Weight Range", "Necropsy Data Link", "Necropsy Measurements", "Final Humane Kill", "Valid", "Bag ID", "Review Status", "Notes", "Excluded", "Exclusion Reason"],
    "Followups": ["Follow-up ID", "Follow-up Type", "Site ID", "Trap ID", "Visit ID", "Window ID", "Bag ID", "Created Time", "Priority", "Reason", "Data Required", "Status", "Completed Time", "Notes"],
    "Audit Log": ["Change ID", "Changed Time", "Record Type", "Record ID", "Field", "Previous Value", "New Value", "Reason"],
    "Photos": ["Photo ID", "Check ID", "Follow-up ID", "Window ID", "Trap ID", "Site ID", "Bag ID", "Capture Time", "Photo Type", "File Path", "Notes"],
    # Derived, read-only sheets - documentation written from code, never a
    # second source of truth. See _derived_sheet_data() for what populates
    # them; no UI form or widget may write to either.
    "Trial Config": ["Parameter", "Value", "Source", "Set Date"],
    "Kills": ["Window ID", "Trap ID", "Site ID", "Build Version", "Kill Time", "Final Humane Kill", "Interaction To Kill Min", "Necropsy Assessment", "Animal Weight Range", "Bag ID"],
}

FINDINGS = ["Trap still set, no animal", "Dead animal found", "Trap fired, no animal", "Trap disturbed", "Trap missing", "Unable to check"]
LURE = ["Fresh", "Present/good", "Partly eaten", "Gone", "Dry", "Mouldy", "Contaminated", "Unknown"]
CAMERA = ["Working", "Offline", "Battery low", "Poor view", "Blocked view", "Missing", "Unsure"]
SPECIES = ["Rat", "Mouse", "Non-target", "Unknown"]
ANIMAL_CONDITION = ["Dead and apparently normal", "Dead with obvious injury concern", "Alive and trapped", "Alive and maimed", "Unable to assess"]
RAT_WEIGHT_RANGES = ["0–50 g", "51–100 g", "101–150 g", "151–200 g", "201–250 g", "251–300 g", "301–350 g", "351–400 g", "400+ g"]
MOUSE_WEIGHT_RANGES = ["0–10 g", "11–20 g", "21–30 g", "31+ g"]
RAT_TYPES = ["Norway rat", "Ship rat", "Unclear"]


def weight_ranges_for_species(species) -> list:
    """Mice get their own, much smaller scale; every other species (Rat,
    Non-target, Unknown, or missing) keeps today's rat scale — additive
    for mice only, not a behaviour change for anything else."""
    return MOUSE_WEIGHT_RANGES if species == "Mouse" else RAT_WEIGHT_RANGES


NZ_TZ = ZoneInfo("Pacific/Auckland")


def now() -> datetime:
    """Current New Zealand local time, as a naive datetime.

    datetime.now() with no tz argument returns the *server's* system clock —
    UTC on Render, 12 hours behind NZST (confirmed field bug, 7 Aug 2026).
    datetime.now(NZ_TZ) fixes that and handles the NZDT/NZST daylight-saving
    transition automatically (a hardcoded +12 offset would silently break
    again at the next transition). tzinfo is stripped before returning
    rather than kept aware: every stored timestamp in the workbook is a
    naive string (dtstr/parse_dt never touch tzinfo), and this function is
    compared against and combined with those naive values at 15+ call sites
    throughout the app. Returning a naive datetime with already-correct NZ
    wall-clock values means every one of those existing comparisons keeps
    working unchanged, rather than needing every call site individually
    audited and patched for a naive-vs-aware TypeError.
    """
    return datetime.now(NZ_TZ).replace(microsecond=0, tzinfo=None)


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


def permanently_remove_site(data: Dict[str, pd.DataFrame], site_id: str, reason: str) -> Dict[str, int]:
    """Permanently delete a site and every record tied to it - Sites, Traps,
    Visits, Windows, Followups, Checks and Photos (plus their evidence
    files on disk).

    Every other removal tool in this app (delete_unused_trap,
    remove_unused_build) deliberately only works when there's no real
    history to lose - by design, this app otherwise never deletes trial
    history (Trial setup's own helper text: "Historical visit and result
    records are preserved"). This is the one deliberate exception, built
    for R1_M1_Agreed_Release_Sequence_Updated.md's "remove remaining
    bundled demo records safely": bundled demo sites carry fabricated
    kills and results that were never real trial data in the first place,
    and leaving them live corrupts real Trial Performance numbers by
    definition (confirmed live: 3 fabricated rat kills were already being
    counted alongside real results before this).

    Guarded accordingly - the site must already be Inactive (can't pull a
    site out from under a field operator mid-use), and reason is
    mandatory. Unlike delete_unused_trap's silent removal, this always
    writes one Audit Log entry with a per-sheet count of what was removed,
    so what happened and why is never silently lost even though the
    underlying rows are gone for good.

    Checks isn't in SITE_CODE_LINKED_SHEETS (it carries Trap ID, not Site
    ID), so it's matched separately via the site's own trap IDs rather
    than reusing site_code_link_counts() for that one sheet.
    """
    if not reason.strip():
        raise ValueError("Enter a reason for removing this site.")
    site_code = normalise_site_code(site_id)
    matches = data["Sites"][data["Sites"]["Site ID"].astype(str).str.upper() == site_code]
    if matches.empty:
        raise ValueError("That site could not be found.")
    site_row = matches.iloc[0]
    if str(site_row["Status"]) != "Inactive":
        raise ValueError("Set this site to Inactive before removing it.")

    counts = site_code_link_counts(data, site_code)
    trap_ids = set(
        data["Traps"][data["Traps"]["Site ID"].astype(str).str.upper() == site_code]["Trap ID"].astype(str)
    )

    updated = {name: frame.copy(deep=True) for name, frame in data.items()}

    checks_removed = 0
    checks_frame = updated.get("Checks")
    if checks_frame is not None and "Trap ID" in checks_frame.columns and trap_ids:
        checks_mask = checks_frame["Trap ID"].astype(str).isin(trap_ids)
        checks_removed = int(checks_mask.sum())
        updated["Checks"] = checks_frame.loc[~checks_mask].reset_index(drop=True)
    counts["Checks"] = checks_removed

    photo_files_to_delete = []
    photos_frame = updated.get("Photos")
    if photos_frame is not None and "Site ID" in photos_frame.columns:
        photo_mask = photos_frame["Site ID"].astype(str).str.upper() == site_code
        for _, prow in photos_frame.loc[photo_mask].iterrows():
            rel_path = _safe_relative_photo_path(prow.get("File Path", ""))
            if rel_path is not None:
                photo_files_to_delete.append(DATA_ROOT / rel_path)
        updated["Photos"] = photos_frame.loc[~photo_mask].reset_index(drop=True)

    for sheet_name in ["Traps", "Visits", "Windows", "Followups"]:
        frame = updated.get(sheet_name)
        if frame is None or "Site ID" not in frame.columns:
            continue
        mask = frame["Site ID"].astype(str).str.upper() == site_code
        updated[sheet_name] = frame.loc[~mask].reset_index(drop=True)

    updated["Sites"] = updated["Sites"].loc[
        updated["Sites"]["Site ID"].astype(str).str.upper() != site_code
    ].reset_index(drop=True)

    detail = ", ".join(f"{name}: {count}" for name, count in counts.items() if count)
    audit_change(
        updated, "Site", site_code, "Permanently removed",
        str(site_row["Site Name"]), "",
        f"{reason.strip()} | Records removed: {detail}" if detail else reason.strip(),
    )

    # Data first, files after: if save_data fails, the exception propagates
    # and no file has been touched - the workbook still references
    # everything exactly as before. Only delete evidence files once the
    # record removal itself is safely persisted.
    save_data(updated)
    for path in photo_files_to_delete:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    remove_empty_evidence_directories(site_code)

    for name in data:
        data[name] = updated[name]
    return counts


def next_bag_id(data, site_id: str) -> str:
    prefix = (site_id or "BAG").upper()[:3]
    existing = pd.concat([data["Checks"].get("Bag ID", pd.Series(dtype=str)), data["Windows"].get("Bag ID", pd.Series(dtype=str))], ignore_index=True).astype(str)
    used = set(existing[existing.str.match(rf"^{prefix}-\d{{3}}$")].tolist())
    number = 1
    while f"{prefix}-{number:03d}" in used:
        number += 1
    return f"{prefix}-{number:03d}"


def followup_genuinely_warranted(w) -> bool:
    """True if this window's own data calls for a Camera/Necropsy review, independent
    of whether a follow-up task currently exists - mirrors the conditions add_followup's
    callers use to create those tasks in the first place. A dead-animal window only
    still needs a necropsy review while Final Humane Kill is Pending - once that's set
    (e.g. entered directly via the Corrections necropsy-evidence path, which legitimately
    never creates a follow-up row), the review is genuinely done, not missing."""
    finding = w["Finding At Close"]
    assessable = finding not in ["Trap missing", "Unable to check"]
    necropsy_warranted = finding == "Dead animal found" and w["Final Humane Kill"] == "Pending"
    camera_warranted = assessable and w["Camera Assigned"] == "Yes"
    return necropsy_warranted or camera_warranted


def refresh_review_status(data, window_id: str) -> None:
    if not window_id:
        return
    idxs = data["Windows"].index[data["Windows"]["Window ID"] == window_id].tolist()
    if not idxs:
        return
    tasks = data["Followups"][(data["Followups"]["Window ID"] == window_id) & (data["Followups"]["Follow-up Type"].isin(["Camera review", "Necropsy review"]))]
    if tasks.empty:
        # An empty task list only means "not required" if a review was never warranted -
        # otherwise a removed/lost task must not be read as "nothing further to do".
        w = data["Windows"].loc[idxs[0]]
        status = "Needs recreation" if followup_genuinely_warranted(w) else "Not required"
    elif (tasks["Status"] == "Open").any():
        status = "Open"
    else:
        status = "Complete"
    data["Windows"].at[idxs[0], "Review Status"] = status


def missing_followup_windows(data) -> pd.DataFrame:
    """Closed windows whose own data genuinely warrants a Camera/Necropsy review but
    that currently have no such follow-up task linked - whether freshly orphaned
    (Review Status 'Needs recreation') or a legacy row saved before that status
    existed (still showing the earlier, incorrect 'Not required' label). Recomputed
    from the underlying data rather than trusting the stored label, so it finds both."""
    windows = data["Windows"]
    closed = windows[windows["Status"] == "Closed"]
    if closed.empty:
        return closed
    linked_window_ids = set(
        data["Followups"][data["Followups"]["Follow-up Type"].isin(["Camera review", "Necropsy review"])]["Window ID"].astype(str)
    )
    missing = ~closed["Window ID"].astype(str).isin(linked_window_ids)
    warranted = closed.apply(followup_genuinely_warranted, axis=1)
    return closed[missing & warranted]


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

# Workflow context mirrored to the URL so a dropped/reconnected session (the
# patchy-field-signal failure mode) has something to restore from. Key names
# are distinct from AUTH_QUERY_KEY and from each other on purpose, so a
# single-key `st.query_params[key] = value` assignment (as require_authentication
# already does) can never collide with these.
WORKFLOW_QUERY_KEY_PAGE = "wf_page"
WORKFLOW_QUERY_KEY_SITE = "wf_site"
WORKFLOW_QUERY_KEY_VISIT = "wf_visit"
WORKFLOW_QUERY_KEY_TRAP = "wf_trap"
WORKFLOW_CONTEXT_QUERY_KEYS = {
    "site_id": WORKFLOW_QUERY_KEY_SITE,
    "visit_id": WORKFLOW_QUERY_KEY_VISIT,
    "trap_id": WORKFLOW_QUERY_KEY_TRAP,
}


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
    effective_data = data
    try:
        derived = _derived_sheet_data(data)
        effective_data = {**data, **derived}
    except Exception:
        # Trial Config / Kills are read-only, derived-for-convenience sheets -
        # a bug computing them must never block or corrupt the save of every
        # other sheet in the workbook. Fall back to whatever was already in
        # `data` for these two keys (blank if never set) and save everything
        # else as normal.
        _logger.exception("Failed to compute derived Trial Config / Kills sheets; saving without updating them.")
    try:
        with pd.ExcelWriter(temp_file, engine="openpyxl") as writer:
            for name, cols in SHEETS.items():
                df = effective_data.get(name, blank(name)).copy()
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


def _data_file_mtime() -> float:
    try:
        return DATA_FILE.stat().st_mtime
    except FileNotFoundError:
        return 0.0


@st.cache_data(show_spinner=False)
def _load_data_cached(mtime: float) -> Dict[str, pd.DataFrame]:
    xl = pd.ExcelFile(DATA_FILE)
    out = {}
    for name, cols in SHEETS.items():
        try:
            df = xl.parse(sheet_name=name, dtype=str).fillna("")
        except Exception:
            df = blank(name)
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        out[name] = df[cols]
    return out


def load_data() -> Dict[str, pd.DataFrame]:
    ensure_storage_ready()
    if not DATA_FILE.exists() and SEED_DATA_FILE.exists() and SEED_DATA_FILE != DATA_FILE:
        shutil.copy2(SEED_DATA_FILE, DATA_FILE)
    if not DATA_FILE.exists():
        data = create_sample_data(); save_data(data); return data
    return _load_data_cached(_data_file_mtime())


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


TIMEZONE_CORRECTIONS = [
    ('Checks', 'Check ID', 'CHK-20260803-031507-1297', 'Check Time', '2026-08-03 03:14:59', '2026-08-03 15:14:59'),
    ('Checks', 'Check ID', 'CHK-20260803-053023-FEFC', 'Check Time', '2026-08-03 05:30:15', '2026-08-03 17:30:15'),
    ('Checks', 'Check ID', 'CHK-20260805-030030-5DA4', 'Check Time', '2026-08-05 03:00:27', '2026-08-05 15:00:27'),
    ('Checks', 'Check ID', 'CHK-20260806-012619-95D8', 'Check Time', '2026-08-06 01:26:16', '2026-08-06 13:26:16'),
    ('Checks', 'Check ID', 'CHK-20260806-025308-C3A4', 'Check Time', '2026-08-06 02:52:55', '2026-08-06 14:52:55'),
    ('Checks', 'Check ID', 'CHK-20260806-030022-84FF', 'Check Time', '2026-08-06 03:00:18', '2026-08-06 15:00:18'),
    ('Checks', 'Check ID', 'CHK-20260806-031157-3E7C', 'Check Time', '2026-08-06 03:11:55', '2026-08-06 15:11:55'),
    ('Checks', 'Check ID', 'CHK-20260806-031702-20AF', 'Check Time', '2026-08-06 03:16:57', '2026-08-06 15:16:57'),
    ('Checks', 'Check ID', 'CHK-20260806-032231-68A2', 'Check Time', '2026-08-06 03:22:27', '2026-08-06 15:22:27'),
    ('Checks', 'Check ID', 'CHK-20260806-033030-EEE6', 'Check Time', '2026-08-06 03:30:24', '2026-08-06 15:30:24'),
    ('Checks', 'Check ID', 'CHK-20260806-033635-BAD3', 'Check Time', '2026-08-06 03:36:28', '2026-08-06 15:36:28'),
    ('Checks', 'Check ID', 'CHK-20260806-040331-180D', 'Check Time', '2026-08-06 04:03:29', '2026-08-06 16:03:29'),
    ('Checks', 'Check ID', 'CHK-20260806-040618-66D8', 'Check Time', '2026-08-06 04:06:15', '2026-08-06 16:06:15'),
    ('Checks', 'Check ID', 'CHK-20260806-040826-9FFC', 'Check Time', '2026-08-06 04:08:17', '2026-08-06 16:08:17'),
    ('Checks', 'Check ID', 'CHK-20260806-040950-1608', 'Check Time', '2026-08-06 04:09:47', '2026-08-06 16:09:47'),
    ('Checks', 'Check ID', 'CHK-20260806-041629-6228', 'Check Time', '2026-08-06 04:16:21', '2026-08-06 16:16:21'),
    ('Checks', 'Check ID', 'CHK-20260806-041848-998C', 'Check Time', '2026-08-06 04:18:46', '2026-08-06 16:18:46'),
    ('Checks', 'Check ID', 'CHK-20260806-042332-D813', 'Check Time', '2026-08-06 04:23:29', '2026-08-06 16:23:29'),
    ('Checks', 'Check ID', 'CHK-20260806-042840-6F2F', 'Check Time', '2026-08-06 04:28:38', '2026-08-06 16:28:38'),
    ('Checks', 'Check ID', 'CHK-20260806-043056-A192', 'Check Time', '2026-08-06 04:30:54', '2026-08-06 16:30:54'),
    ('Checks', 'Check ID', 'CHK-20260806-043222-D7DA', 'Check Time', '2026-08-06 04:32:18', '2026-08-06 16:32:18'),
    ('Checks', 'Check ID', 'CHK-20260806-080152-D55B', 'Check Time', '2026-08-06 08:01:52', '2026-08-06 20:01:52'),
    ('Checks', 'Check ID', 'CHK-20260806-080203-C619', 'Check Time', '2026-08-06 08:02:03', '2026-08-06 20:02:03'),
    ('Checks', 'Check ID', 'CHK-20260806-083030-3411', 'Check Time', '2026-08-06 08:30:30', '2026-08-06 20:30:30'),
    ('Checks', 'Check ID', 'CHK-20260806-083339-C29E', 'Check Time', '2026-08-06 08:33:39', '2026-08-06 20:33:39'),
    ('Checks', 'Check ID', 'CHK-20260806-192616-953F', 'Check Time', '2026-08-06 19:26:16', '2026-08-07 07:26:16'),
    ('Checks', 'Check ID', 'CHK-20260806-192627-085A', 'Check Time', '2026-08-06 19:26:27', '2026-08-07 07:26:27'),
    ('Checks', 'Check ID', 'CHK-20260806-192634-D363', 'Check Time', '2026-08-06 19:26:34', '2026-08-07 07:26:34'),
    ('Checks', 'Check ID', 'CHK-20260806-192642-7E9D', 'Check Time', '2026-08-06 19:26:42', '2026-08-07 07:26:42'),
    ('Checks', 'Check ID', 'CHK-20260806-192649-A3E2', 'Check Time', '2026-08-06 19:26:49', '2026-08-07 07:26:49'),
    ('Checks', 'Check ID', 'CHK-20260806-192656-EAF6', 'Check Time', '2026-08-06 19:26:56', '2026-08-07 07:26:56'),
    ('Checks', 'Check ID', 'CHK-20260806-192703-FEC0', 'Check Time', '2026-08-06 19:27:03', '2026-08-07 07:27:03'),
    ('Checks', 'Check ID', 'CHK-20260806-192711-2E98', 'Check Time', '2026-08-06 19:27:11', '2026-08-07 07:27:11'),
    ('Checks', 'Check ID', 'CHK-20260806-233518-2DC8', 'Check Time', '2026-08-06 23:35:18', '2026-08-07 11:35:18'),
    ('Checks', 'Check ID', 'CHK-20260806-233656-E60C', 'Check Time', '2026-08-06 23:36:56', '2026-08-07 11:36:56'),
    ('Checks', 'Check ID', 'CHK-20260806-233808-E0DA', 'Check Time', '2026-08-06 23:38:08', '2026-08-07 11:38:08'),
    ('Checks', 'Check ID', 'CHK-20260806-233852-8D44', 'Check Time', '2026-08-06 23:38:52', '2026-08-07 11:38:52'),
    ('Checks', 'Check ID', 'CHK-20260806-233945-694A', 'Check Time', '2026-08-06 23:39:45', '2026-08-07 11:39:45'),
    ('Checks', 'Check ID', 'CHK-20260806-234218-8D35', 'Check Time', '2026-08-06 23:42:18', '2026-08-07 11:42:18'),
    ('Checks', 'Check ID', 'CHK-20260806-234518-33DA', 'Check Time', '2026-08-06 23:45:18', '2026-08-07 11:45:18'),
    ('Checks', 'Check ID', 'CHK-20260806-235826-E6F8', 'Check Time', '2026-08-06 23:58:26', '2026-08-07 11:58:26'),
    ('Checks', 'Check ID', 'CHK-20260807-000143-ED1F', 'Check Time', '2026-08-07 00:01:43', '2026-08-07 12:01:43'),
    ('Checks', 'Check ID', 'CHK-20260807-000325-0259', 'Check Time', '2026-08-07 00:03:25', '2026-08-07 12:03:25'),
    ('Visits', 'Visit ID', 'VIS-HUT-20260803-025834-FD33', 'Start Time', '2026-08-03 02:58:34', '2026-08-03 14:58:34'),
    ('Visits', 'Visit ID', 'VIS-NAE-20260803-050537-887D', 'Start Time', '2026-08-03 05:05:37', '2026-08-03 17:05:37'),
    ('Visits', 'Visit ID', 'VIS-TAW-20260803-052717-642D', 'Start Time', '2026-08-03 05:27:17', '2026-08-03 17:27:17'),
    ('Visits', 'Visit ID', 'VIS-TR-20260806-023919-64C7', 'Start Time', '2026-08-06 02:39:19', '2026-08-06 14:39:19'),
    ('Visits', 'Visit ID', 'VIS-TR-20260806-023919-64C7', 'End Time', '2026-08-06 08:04:11', '2026-08-06 20:04:11'),
    ('Visits', 'Visit ID', 'VIS-MOA-20260806-081624-8D24', 'Start Time', '2026-08-06 08:16:24', '2026-08-06 20:16:24'),
    ('Visits', 'Visit ID', 'VIS-MOA-20260806-081624-8D24', 'End Time', '2026-08-06 08:16:29', '2026-08-06 20:16:29'),
    ('Visits', 'Visit ID', 'VIS-MOA-20260806-081810-1FC1', 'Start Time', '2026-08-06 08:18:10', '2026-08-06 20:18:10'),
    ('Visits', 'Visit ID', 'VIS-MOA-20260806-081810-1FC1', 'End Time', '2026-08-06 08:20:47', '2026-08-06 20:20:47'),
    ('Visits', 'Visit ID', 'VIS-MOA-20260806-082947-DABC', 'Start Time', '2026-08-06 08:29:47', '2026-08-06 20:29:47'),
    ('Visits', 'Visit ID', 'VIS-MOA-20260806-082947-DABC', 'End Time', '2026-08-06 19:27:15', '2026-08-07 07:27:15'),
    ('Visits', 'Visit ID', 'VIS-TR-20260806-224548-9542', 'Start Time', '2026-08-06 22:45:48', '2026-08-07 10:45:48'),
    ('Visits', 'Visit ID', 'VIS-MOA-20260806-233135-1F3F', 'Start Time', '2026-08-06 23:31:35', '2026-08-07 11:31:35'),
    ('Visits', 'Visit ID', 'VIS-MOA-20260806-233135-1F3F', 'End Time', '2026-08-07 00:12:55', '2026-08-07 12:12:55'),
    ('Visits', 'Visit ID', 'VIS-MOA-20260807-074808-40F8', 'Start Time', '2026-08-07 07:48:08', '2026-08-07 19:48:08'),
    ('Visits', 'Visit ID', 'VIS-MOA-20260807-074808-40F8', 'End Time', '2026-08-07 19:27:39', '2026-08-08 07:27:39'),
    ('Windows', 'Window ID', 'R1-HUT-001-W-LAUNCH-01', 'End Time', '2026-08-03 03:14:59', '2026-08-03 15:14:59'),
    ('Windows', 'Window ID', 'R1-HUT-002-W-LAUNCH-01', 'End Time', '2026-08-03 05:30:15', '2026-08-03 17:30:15'),
    ('Windows', 'Window ID', 'R1-HUT-003-W-LAUNCH-01', 'End Time', '2026-08-05 03:00:27', '2026-08-05 15:00:27'),
    ('Windows', 'Window ID', 'R1-HUT-004-W-LAUNCH-01', 'End Time', '2026-08-06 01:26:16', '2026-08-06 13:26:16'),
    ('Windows', 'Window ID', 'R1-HUT-001-W-20260803-031507-B85D', 'Start Time', '2026-08-03 03:14:59', '2026-08-03 15:14:59'),
    ('Windows', 'Window ID', 'R1-HUT-002-W-20260803-053023-9B96', 'Start Time', '2026-08-03 05:30:15', '2026-08-03 17:30:15'),
    ('Windows', 'Window ID', 'R1-HUT-003-W-20260805-030030-23F4', 'Start Time', '2026-08-05 03:00:27', '2026-08-05 15:00:27'),
    ('Windows', 'Window ID', 'R1-HUT-004-W-20260806-012619-C4BF', 'Start Time', '2026-08-06 01:26:16', '2026-08-06 13:26:16'),
    ('Windows', 'Window ID', 'R15-3-W-20260806-015048-BF13', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'R15-3-W-20260806-015048-BF13', 'End Time', '2026-08-06 03:36:28', '2026-08-06 15:36:28'),
    ('Windows', 'Window ID', 'R15-4-W-20260806-015108-E088', 'Start Time', '2026-08-06 01:51:00', '2026-08-06 13:51:00'),
    ('Windows', 'Window ID', 'R15-4-W-20260806-015108-E088', 'End Time', '2026-08-06 03:00:18', '2026-08-06 15:00:18'),
    ('Windows', 'Window ID', 'R15-5-W-20260806-015130-A21C', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'R15-5-W-20260806-015130-A21C', 'End Time', '2026-08-06 03:22:27', '2026-08-06 15:22:27'),
    ('Windows', 'Window ID', 'R15-6-W-20260806-015204-508A', 'Start Time', '2026-08-06 01:52:00', '2026-08-06 13:52:00'),
    ('Windows', 'Window ID', 'R15-6-W-20260806-015204-508A', 'End Time', '2026-08-06 03:16:57', '2026-08-06 15:16:57'),
    ('Windows', 'Window ID', 'R15-7-W-20260806-015239-50F4', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'R15-7-W-20260806-015239-50F4', 'End Time', '2026-08-06 03:30:24', '2026-08-06 15:30:24'),
    ('Windows', 'Window ID', 'R15-8-W-20260806-015258-9241', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'R15-8-W-20260806-015258-9241', 'End Time', '2026-08-06 03:11:55', '2026-08-06 15:11:55'),
    ('Windows', 'Window ID', 'R15-9-W-20260806-015314-59FA', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'R15-9-W-20260806-015314-59FA', 'End Time', '2026-08-06 02:52:55', '2026-08-06 14:52:55'),
    ('Windows', 'Window ID', 'M15-1-W-20260806-020620-99AD', 'Start Time', '2026-08-06 02:06:00', '2026-08-06 14:06:00'),
    ('Windows', 'Window ID', 'M15-1-W-20260806-020620-99AD', 'End Time', '2026-08-06 04:18:46', '2026-08-06 16:18:46'),
    ('Windows', 'Window ID', 'M15-2-W-20260806-020639-99C5', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'M15-2-W-20260806-020639-99C5', 'End Time', '2026-08-06 04:16:21', '2026-08-06 16:16:21'),
    ('Windows', 'Window ID', 'M15-3-W-20260806-020654-BC9A', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'M15-3-W-20260806-020654-BC9A', 'End Time', '2026-08-06 04:03:29', '2026-08-06 16:03:29'),
    ('Windows', 'Window ID', 'M15-4-W-20260806-020709-E03F', 'Start Time', '2026-08-06 02:07:00', '2026-08-06 14:07:00'),
    ('Windows', 'Window ID', 'M15-4-W-20260806-020709-E03F', 'End Time', '2026-08-06 04:32:18', '2026-08-06 16:32:18'),
    ('Windows', 'Window ID', 'M15-5-W-20260806-020723-F1CE', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'M15-5-W-20260806-020723-F1CE', 'End Time', '2026-08-06 04:06:15', '2026-08-06 16:06:15'),
    ('Windows', 'Window ID', 'M15-6-W-20260806-020741-9ECB', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'M15-6-W-20260806-020741-9ECB', 'End Time', '2026-08-06 04:08:17', '2026-08-06 16:08:17'),
    ('Windows', 'Window ID', 'M15-7-W-20260806-020755-C58E', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'M15-7-W-20260806-020755-C58E', 'End Time', '2026-08-06 04:28:38', '2026-08-06 16:28:38'),
    ('Windows', 'Window ID', 'M15-8-W-20260806-020811-234D', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'M15-8-W-20260806-020811-234D', 'End Time', '2026-08-06 04:23:29', '2026-08-06 16:23:29'),
    ('Windows', 'Window ID', 'M15-9-W-20260806-020826-23E3', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'M15-9-W-20260806-020826-23E3', 'End Time', '2026-08-06 04:30:54', '2026-08-06 16:30:54'),
    ('Windows', 'Window ID', 'M15-10-W-20260806-020841-1687', 'Start Time', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Windows', 'Window ID', 'M15-10-W-20260806-020841-1687', 'End Time', '2026-08-06 04:09:47', '2026-08-06 16:09:47'),
    ('Windows', 'Window ID', 'R15-9-W-20260806-025308-E100', 'Start Time', '2026-08-06 02:52:55', '2026-08-06 14:52:55'),
    ('Windows', 'Window ID', 'R15-4-W-20260806-030022-5D2A', 'Start Time', '2026-08-06 03:00:18', '2026-08-06 15:00:18'),
    ('Windows', 'Window ID', 'R15-8-W-20260806-031157-3216', 'Start Time', '2026-08-06 03:11:55', '2026-08-06 15:11:55'),
    ('Windows', 'Window ID', 'R15-6-W-20260806-031702-486D', 'Start Time', '2026-08-06 03:16:57', '2026-08-06 15:16:57'),
    ('Windows', 'Window ID', 'R15-5-W-20260806-032231-9EFB', 'Start Time', '2026-08-06 03:22:27', '2026-08-06 15:22:27'),
    ('Windows', 'Window ID', 'R15-7-W-20260806-033030-3EA7', 'Start Time', '2026-08-06 03:30:24', '2026-08-06 15:30:24'),
    ('Windows', 'Window ID', 'R15-3-W-20260806-033635-4C8F', 'Start Time', '2026-08-06 03:36:28', '2026-08-06 15:36:28'),
    ('Windows', 'Window ID', 'M15-3-W-20260806-040331-76B7', 'Start Time', '2026-08-06 04:03:29', '2026-08-06 16:03:29'),
    ('Windows', 'Window ID', 'M15-3-W-20260806-040331-76B7', 'End Time', '2026-08-06 08:22:00', '2026-08-06 20:22:00'),
    ('Windows', 'Window ID', 'M15-5-W-20260806-040618-1DDF', 'Start Time', '2026-08-06 04:06:15', '2026-08-06 16:06:15'),
    ('Windows', 'Window ID', 'M15-5-W-20260806-040618-1DDF', 'End Time', '2026-08-06 08:23:00', '2026-08-06 20:23:00'),
    ('Windows', 'Window ID', 'M15-6-W-20260806-040826-229B', 'Start Time', '2026-08-06 04:08:17', '2026-08-06 16:08:17'),
    ('Windows', 'Window ID', 'M15-6-W-20260806-040826-229B', 'End Time', '2026-08-06 08:23:00', '2026-08-06 20:23:00'),
    ('Windows', 'Window ID', 'M15-10-W-20260806-040950-BFC2', 'Start Time', '2026-08-06 04:09:47', '2026-08-06 16:09:47'),
    ('Windows', 'Window ID', 'M15-10-W-20260806-040950-BFC2', 'End Time', '2026-08-06 08:24:00', '2026-08-06 20:24:00'),
    ('Windows', 'Window ID', 'M15-2-W-20260806-041629-5E2F', 'Start Time', '2026-08-06 04:16:21', '2026-08-06 16:16:21'),
    ('Windows', 'Window ID', 'M15-2-W-20260806-041629-5E2F', 'End Time', '2026-08-06 08:21:00', '2026-08-06 20:21:00'),
    ('Windows', 'Window ID', 'M15-1-W-20260806-041848-5311', 'Start Time', '2026-08-06 04:18:46', '2026-08-06 16:18:46'),
    ('Windows', 'Window ID', 'M15-1-W-20260806-041848-5311', 'End Time', '2026-08-06 08:21:00', '2026-08-06 20:21:00'),
    ('Windows', 'Window ID', 'M15-8-W-20260806-042332-D71F', 'Start Time', '2026-08-06 04:23:29', '2026-08-06 16:23:29'),
    ('Windows', 'Window ID', 'M15-8-W-20260806-042332-D71F', 'End Time', '2026-08-06 08:24:00', '2026-08-06 20:24:00'),
    ('Windows', 'Window ID', 'M15-7-W-20260806-042840-E469', 'Start Time', '2026-08-06 04:28:38', '2026-08-06 16:28:38'),
    ('Windows', 'Window ID', 'M15-7-W-20260806-042840-E469', 'End Time', '2026-08-06 08:23:00', '2026-08-06 20:23:00'),
    ('Windows', 'Window ID', 'M15-9-W-20260806-043056-C2DC', 'Start Time', '2026-08-06 04:30:54', '2026-08-06 16:30:54'),
    ('Windows', 'Window ID', 'M15-9-W-20260806-043056-C2DC', 'End Time', '2026-08-06 08:24:00', '2026-08-06 20:24:00'),
    ('Windows', 'Window ID', 'M15-4-W-20260806-043222-08C7', 'Start Time', '2026-08-06 04:32:18', '2026-08-06 16:32:18'),
    ('Windows', 'Window ID', 'M15-4-W-20260806-043222-08C7', 'End Time', '2026-08-06 08:22:00', '2026-08-06 20:22:00'),
    ('Windows', 'Window ID', 'R15-1-W-20260806-080144-3AA7', 'Start Time', '2026-07-31 04:00:00', '2026-07-31 16:00:00'),
    ('Windows', 'Window ID', 'R15-1-W-20260806-080144-3AA7', 'End Time', '2026-08-06 08:01:52', '2026-08-06 20:01:52'),
    ('Windows', 'Window ID', 'R15-1-W-20260806-080152-C25D', 'Start Time', '2026-08-06 08:01:52', '2026-08-06 20:01:52'),
    ('Windows', 'Window ID', 'R15-2-W-20260806-080156-C0AF', 'Start Time', '2026-07-31 03:00:00', '2026-07-31 15:00:00'),
    ('Windows', 'Window ID', 'R15-2-W-20260806-080156-C0AF', 'End Time', '2026-08-06 08:02:03', '2026-08-06 20:02:03'),
    ('Windows', 'Window ID', 'R15-2-W-20260806-080203-9D3A', 'Start Time', '2026-08-06 08:02:03', '2026-08-06 20:02:03'),
    ('Windows', 'Window ID', 'M15-1-W-20260806-082109-699D', 'Start Time', '2026-08-06 08:21:00', '2026-08-06 20:21:00'),
    ('Windows', 'Window ID', 'M15-1-W-20260806-082109-699D', 'End Time', '2026-08-06 08:30:30', '2026-08-06 20:30:30'),
    ('Windows', 'Window ID', 'M15-2-W-20260806-082152-B472', 'Start Time', '2026-08-06 08:21:00', '2026-08-06 20:21:00'),
    ('Windows', 'Window ID', 'M15-2-W-20260806-082152-B472', 'End Time', '2026-08-06 19:26:27', '2026-08-07 07:26:27'),
    ('Windows', 'Window ID', 'M15-3-W-20260806-082230-AD60', 'Start Time', '2026-08-06 08:22:00', '2026-08-06 20:22:00'),
    ('Windows', 'Window ID', 'M15-3-W-20260806-082230-AD60', 'End Time', '2026-08-06 19:26:34', '2026-08-07 07:26:34'),
    ('Windows', 'Window ID', 'M15-4-W-20260806-082256-7270', 'Start Time', '2026-08-06 08:22:00', '2026-08-06 20:22:00'),
    ('Windows', 'Window ID', 'M15-4-W-20260806-082256-7270', 'End Time', '2026-08-06 19:26:42', '2026-08-07 07:26:42'),
    ('Windows', 'Window ID', 'M15-5-W-20260806-082322-10F4', 'Start Time', '2026-08-06 08:23:00', '2026-08-06 20:23:00'),
    ('Windows', 'Window ID', 'M15-5-W-20260806-082322-10F4', 'End Time', '2026-08-06 19:26:49', '2026-08-07 07:26:49'),
    ('Windows', 'Window ID', 'M15-6-W-20260806-082339-8347', 'Start Time', '2026-08-06 08:23:00', '2026-08-06 20:23:00'),
    ('Windows', 'Window ID', 'M15-6-W-20260806-082339-8347', 'End Time', '2026-08-06 19:26:56', '2026-08-07 07:26:56'),
    ('Windows', 'Window ID', 'M15-7-W-20260806-082354-A58E', 'Start Time', '2026-08-06 08:23:00', '2026-08-06 20:23:00'),
    ('Windows', 'Window ID', 'M15-7-W-20260806-082354-A58E', 'End Time', '2026-08-06 19:27:03', '2026-08-07 07:27:03'),
    ('Windows', 'Window ID', 'M15-8-W-20260806-082410-9C04', 'Start Time', '2026-08-06 08:24:00', '2026-08-06 20:24:00'),
    ('Windows', 'Window ID', 'M15-8-W-20260806-082410-9C04', 'End Time', '2026-08-06 19:27:11', '2026-08-07 07:27:11'),
    ('Windows', 'Window ID', 'M15-9-W-20260806-082425-5AD3', 'Start Time', '2026-08-06 08:24:00', '2026-08-06 20:24:00'),
    ('Windows', 'Window ID', 'M15-9-W-20260806-082425-5AD3', 'End Time', '2026-08-06 19:26:16', '2026-08-07 07:26:16'),
    ('Windows', 'Window ID', 'M15-10-W-20260806-082441-C215', 'Start Time', '2026-08-06 08:24:00', '2026-08-06 20:24:00'),
    ('Windows', 'Window ID', 'M15-10-W-20260806-082441-C215', 'End Time', '2026-08-06 08:33:39', '2026-08-06 20:33:39'),
    ('Windows', 'Window ID', 'M15-1-W-20260806-083030-8136', 'Start Time', '2026-08-06 08:30:30', '2026-08-06 20:30:30'),
    ('Windows', 'Window ID', 'M15-1-W-20260806-083030-8136', 'End Time', '2026-08-06 23:42:18', '2026-08-07 11:42:18'),
    ('Windows', 'Window ID', 'M15-10-W-20260806-083339-A18E', 'Start Time', '2026-08-06 08:33:39', '2026-08-06 20:33:39'),
    ('Windows', 'Window ID', 'M15-10-W-20260806-083339-A18E', 'End Time', '2026-08-06 23:38:52', '2026-08-07 11:38:52'),
    ('Windows', 'Window ID', 'M15-9-W-20260806-192616-A004', 'Start Time', '2026-08-06 19:26:16', '2026-08-07 07:26:16'),
    ('Windows', 'Window ID', 'M15-9-W-20260806-192616-A004', 'End Time', '2026-08-07 00:01:43', '2026-08-07 12:01:43'),
    ('Windows', 'Window ID', 'M15-2-W-20260806-192627-2499', 'Start Time', '2026-08-06 19:26:27', '2026-08-07 07:26:27'),
    ('Windows', 'Window ID', 'M15-2-W-20260806-192627-2499', 'End Time', '2026-08-06 23:39:45', '2026-08-07 11:39:45'),
    ('Windows', 'Window ID', 'M15-3-W-20260806-192634-B4CF', 'Start Time', '2026-08-06 19:26:34', '2026-08-07 07:26:34'),
    ('Windows', 'Window ID', 'M15-3-W-20260806-192634-B4CF', 'End Time', '2026-08-06 23:35:18', '2026-08-07 11:35:18'),
    ('Windows', 'Window ID', 'M15-4-W-20260806-192642-F280', 'Start Time', '2026-08-06 19:26:42', '2026-08-07 07:26:42'),
    ('Windows', 'Window ID', 'M15-4-W-20260806-192642-F280', 'End Time', '2026-08-07 00:03:25', '2026-08-07 12:03:25'),
    ('Windows', 'Window ID', 'M15-5-W-20260806-192649-8CA7', 'Start Time', '2026-08-06 19:26:49', '2026-08-07 07:26:49'),
    ('Windows', 'Window ID', 'M15-5-W-20260806-192649-8CA7', 'End Time', '2026-08-06 23:36:56', '2026-08-07 11:36:56'),
    ('Windows', 'Window ID', 'M15-6-W-20260806-192656-D300', 'Start Time', '2026-08-06 19:26:56', '2026-08-07 07:26:56'),
    ('Windows', 'Window ID', 'M15-6-W-20260806-192656-D300', 'End Time', '2026-08-06 23:38:08', '2026-08-07 11:38:08'),
    ('Windows', 'Window ID', 'M15-7-W-20260806-192703-1CFA', 'Start Time', '2026-08-06 19:27:03', '2026-08-07 07:27:03'),
    ('Windows', 'Window ID', 'M15-7-W-20260806-192703-1CFA', 'End Time', '2026-08-06 23:58:26', '2026-08-07 11:58:26'),
    ('Windows', 'Window ID', 'M15-8-W-20260806-192711-0793', 'Start Time', '2026-08-06 19:27:11', '2026-08-07 07:27:11'),
    ('Windows', 'Window ID', 'M15-8-W-20260806-192711-0793', 'End Time', '2026-08-06 23:45:18', '2026-08-07 11:45:18'),
    ('Windows', 'Window ID', 'M15-3-W-20260806-233518-6D74', 'Start Time', '2026-08-06 23:35:18', '2026-08-07 11:35:18'),
    ('Windows', 'Window ID', 'M15-3-W-20260806-233518-6D74', 'End Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-5-W-20260806-233656-3D3E', 'Start Time', '2026-08-06 23:36:56', '2026-08-07 11:36:56'),
    ('Windows', 'Window ID', 'M15-5-W-20260806-233656-3D3E', 'End Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-6-W-20260806-233808-B546', 'Start Time', '2026-08-06 23:38:08', '2026-08-07 11:38:08'),
    ('Windows', 'Window ID', 'M15-6-W-20260806-233808-B546', 'End Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-10-W-20260806-233852-3224', 'Start Time', '2026-08-06 23:38:52', '2026-08-07 11:38:52'),
    ('Windows', 'Window ID', 'M15-10-W-20260806-233852-3224', 'End Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-2-W-20260806-233945-64ED', 'Start Time', '2026-08-06 23:39:45', '2026-08-07 11:39:45'),
    ('Windows', 'Window ID', 'M15-2-W-20260806-233945-64ED', 'End Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-1-W-20260806-234218-B4BA', 'Start Time', '2026-08-06 23:42:18', '2026-08-07 11:42:18'),
    ('Windows', 'Window ID', 'M15-1-W-20260806-234218-B4BA', 'End Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-8-W-20260806-234518-F9AF', 'Start Time', '2026-08-06 23:45:18', '2026-08-07 11:45:18'),
    ('Windows', 'Window ID', 'M15-8-W-20260806-234518-F9AF', 'End Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-7-W-20260806-235826-D495', 'Start Time', '2026-08-06 23:58:26', '2026-08-07 11:58:26'),
    ('Windows', 'Window ID', 'M15-7-W-20260806-235826-D495', 'End Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-9-W-20260807-000143-5EEC', 'Start Time', '2026-08-07 00:01:43', '2026-08-07 12:01:43'),
    ('Windows', 'Window ID', 'M15-9-W-20260807-000143-5EEC', 'End Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-4-W-20260807-000325-2E42', 'Start Time', '2026-08-07 00:03:25', '2026-08-07 12:03:25'),
    ('Windows', 'Window ID', 'M15-4-W-20260807-000325-2E42', 'End Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-3-W-20260807-190623-49D7', 'Start Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-5-W-20260807-190731-A15E', 'Start Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-1-W-20260807-191038-6F02', 'Start Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-8-W-20260807-191244-D1C3', 'Start Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-7-W-20260807-191514-9A14', 'Start Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-9-W-20260807-191905-2C99', 'Start Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-4-W-20260807-192017-A09A', 'Start Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-2-W-20260807-192446-BCB3', 'Start Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-10-W-20260807-192540-1B9E', 'Start Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Windows', 'Window ID', 'M15-6-W-20260807-192728-DB60', 'Start Time', '2026-08-08 07:00:00', '2026-08-08 19:00:00'),
    ('Traps', 'Trap ID', 'R15-1', 'Deployment Start', '2026-07-31 04:00:00', '2026-07-31 16:00:00'),
    ('Traps', 'Trap ID', 'R15-2', 'Deployment Start', '2026-07-31 03:00:00', '2026-07-31 15:00:00'),
    ('Traps', 'Trap ID', 'R15-3', 'Deployment Start', '2026-07-31 04:00:00', '2026-07-31 16:00:00'),
    ('Traps', 'Trap ID', 'R15-4', 'Deployment Start', '2026-08-05 04:00:00', '2026-08-05 16:00:00'),
    ('Traps', 'Trap ID', 'R15-5', 'Deployment Start', '2026-08-05 04:00:00', '2026-08-05 16:00:00'),
    ('Traps', 'Trap ID', 'R15-6', 'Deployment Start', '2026-08-05 04:00:00', '2026-08-05 16:00:00'),
    ('Traps', 'Trap ID', 'R15-7', 'Deployment Start', '2026-08-05 04:00:00', '2026-08-05 16:00:00'),
    ('Traps', 'Trap ID', 'R15-8', 'Deployment Start', '2026-08-05 04:00:00', '2026-08-05 16:00:00'),
    ('Traps', 'Trap ID', 'R15-9', 'Deployment Start', '2026-08-05 04:00:00', '2026-08-05 16:00:00'),
    ('Traps', 'Trap ID', 'M15-1', 'Deployment Start', '2026-08-06 02:06:00', '2026-08-06 14:06:00'),
    ('Traps', 'Trap ID', 'M15-2', 'Deployment Start', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Traps', 'Trap ID', 'M15-3', 'Deployment Start', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Traps', 'Trap ID', 'M15-4', 'Deployment Start', '2026-08-06 02:07:00', '2026-08-06 14:07:00'),
    ('Traps', 'Trap ID', 'M15-5', 'Deployment Start', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Traps', 'Trap ID', 'M15-6', 'Deployment Start', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Traps', 'Trap ID', 'M15-7', 'Deployment Start', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Traps', 'Trap ID', 'M15-8', 'Deployment Start', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Traps', 'Trap ID', 'M15-9', 'Deployment Start', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Traps', 'Trap ID', 'M15-10', 'Deployment Start', '2026-08-06 02:30:00', '2026-08-06 14:30:00'),
    ('Followups', 'Follow-up ID', 'FU-20260806-025308-BC6B', 'Created Time', '2026-08-06 02:53:08', '2026-08-06 14:53:08'),
    ('Followups', 'Follow-up ID', 'FU-20260806-025308-394E', 'Created Time', '2026-08-06 02:53:08', '2026-08-06 14:53:08'),
    ('Followups', 'Follow-up ID', 'FU-20260806-030022-39C9', 'Created Time', '2026-08-06 03:00:22', '2026-08-06 15:00:22'),
    ('Followups', 'Follow-up ID', 'FU-20260806-030022-5360', 'Created Time', '2026-08-06 03:00:22', '2026-08-06 15:00:22'),
    ('Followups', 'Follow-up ID', 'FU-20260806-031157-F1B5', 'Created Time', '2026-08-06 03:11:57', '2026-08-06 15:11:57'),
    ('Followups', 'Follow-up ID', 'FU-20260806-031702-D6B5', 'Created Time', '2026-08-06 03:17:02', '2026-08-06 15:17:02'),
    ('Followups', 'Follow-up ID', 'FU-20260806-032231-D853', 'Created Time', '2026-08-06 03:22:31', '2026-08-06 15:22:31'),
    ('Followups', 'Follow-up ID', 'FU-20260806-033030-DB3A', 'Created Time', '2026-08-06 03:30:30', '2026-08-06 15:30:30'),
    ('Followups', 'Follow-up ID', 'FU-20260806-033635-B4B9', 'Created Time', '2026-08-06 03:36:35', '2026-08-06 15:36:35'),
    ('Followups', 'Follow-up ID', 'FU-20260806-080152-A023', 'Created Time', '2026-08-06 08:01:52', '2026-08-06 20:01:52'),
    ('Followups', 'Follow-up ID', 'FU-20260806-080203-C3FA', 'Created Time', '2026-08-06 08:02:03', '2026-08-06 20:02:03'),
    ('Followups', 'Follow-up ID', 'FU-20260806-234518-5060', 'Created Time', '2026-08-06 23:45:18', '2026-08-07 11:45:18'),
    ('Followups', 'Follow-up ID', 'FU-20260806-235826-7FF3', 'Created Time', '2026-08-06 23:58:26', '2026-08-07 11:58:26'),
    ('Followups', 'Follow-up ID', 'FU-20260807-000143-67F8', 'Created Time', '2026-08-07 00:01:43', '2026-08-07 12:01:43'),
    ('Photos', 'Photo ID', 'PHOTO-20260806-025309-F243', 'Capture Time', '2026-08-06 02:52:10', '2026-08-06 14:52:10'),
    ('Photos', 'Photo ID', 'PHOTO-20260806-025310-13CE', 'Capture Time', '2026-08-06 02:52:10', '2026-08-06 14:52:10'),
    ('Photos', 'Photo ID', 'PHOTO-20260806-025311-1422', 'Capture Time', '2026-08-06 02:52:10', '2026-08-06 14:52:10'),
    ('Photos', 'Photo ID', 'PHOTO-20260806-025313-9B8F', 'Capture Time', '2026-08-06 02:52:10', '2026-08-06 14:52:10'),
    ('Photos', 'Photo ID', 'PHOTO-20260806-083339-50DB', 'Capture Time', '2026-08-06 08:33:13', '2026-08-06 20:33:13'),
    ('Photos', 'Photo ID', 'PHOTO-20260806-083340-F6FE', 'Capture Time', '2026-08-06 08:33:13', '2026-08-06 20:33:13'),
    ('Photos', 'Photo ID', 'PHOTO-20260806-083341-9209', 'Capture Time', '2026-08-06 08:33:13', '2026-08-06 20:33:13'),
]


TIMEZONE_CORRECTION_REASON = (
    "One-time correction: server clock was UTC treated as NZ local "
    "(DATA_INTEGRITY_BRIEF_timezone.md, 8 Aug 2026). Uniform +12h shift to "
    "every historical timestamp recorded before the now() fix, excluding "
    "already-corrected Check Time entries and static seed-baseline values."
)

TIMEZONE_CORRECTION_RECORD_TYPE = {
    "Checks": "Check",
    "Visits": "Visit",
    "Windows": "Window",
    "Traps": "Trap",
    "Followups": "Follow-up",
    "Photos": "Photo",
}


def apply_timezone_correction_migration(data) -> bool:
    """One-time historical data correction for the NZ-timezone now() bug.

    Idempotent: checks the Audit Log for its own marker reason before doing
    anything, so this safely no-ops on every run after the first, across
    restarts and redeploys alike. Left in the codebase permanently as a
    record of what happened, even though it will only ever fire once — the
    Audit Log itself is the durable "has this run" flag, not session state
    or a separate sentinel file.

    Matches rows by ID, but deliberately will NOT touch a field unless its
    CURRENT value exactly equals the recorded old_val first. This ID-only
    matching is not on its own enough to be safe: these IDs are
    deterministic (e.g. "...-W-LAUNCH-01"), so a fresh clean-seed
    deployment has rows with the *same* IDs but unrelated content (in
    testing, a clean-seed run without this guard silently overwrote empty
    seed End Time fields with this correction's hardcoded values, just
    because the Window ID happened to match). The value check is what
    makes this safe to run against any environment, not just the one real
    dataset it was built from — and it also protects the real data itself
    if anything changed between when this list was generated and when it
    deploys.
    """
    if (data["Audit Log"]["Reason"].astype(str) == TIMEZONE_CORRECTION_REASON).any():
        return False
    applied = 0
    for sheet, id_col, id_val, field, old_val, new_val in TIMEZONE_CORRECTIONS:
        idx = data[sheet].index[data[sheet][id_col].astype(str) == str(id_val)]
        if len(idx) == 0:
            continue
        i = idx[0]
        current = data[sheet].at[i, field]
        current_str = "" if pd.isna(current) else str(current).strip()
        if current_str and current_str != old_val:
            try:
                current_str = pd.to_datetime(current).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        if current_str != old_val:
            continue
        data[sheet].at[i, field] = new_val
        audit_change(
            data, TIMEZONE_CORRECTION_RECORD_TYPE[sheet], id_val, field,
            old_val, new_val, TIMEZONE_CORRECTION_REASON,
        )
        applied += 1
    if applied:
        save_data(data)
    return applied > 0


MOUSE_WEIGHT_RECLASSIFICATION_REASON = "Reclassified to the new mouse weight scale"


def apply_mouse_weight_reclassification_migration(data) -> bool:
    """One-time historical data correction for mice recorded before mouse
    and rat weights had separate scales: any Mouse-species window whose
    recorded weight is still one of the old shared rat-scale bands (e.g.
    "51–100 g") gets moved to the lowest mouse band, "0–10 g", per the
    reclassification decision made alongside splitting the two scales.

    Naturally idempotent, unlike apply_timezone_correction_migration above
    - no separate "have I run" marker needed. The match condition itself
    (Species is Mouse AND the weight is still a RAT_WEIGHT_RANGES value)
    can only ever be true for pre-existing data: once this ships, the
    necropsy form and the Corrections form both pick the option list from
    the window's Species, so a Mouse window can never organically be
    assigned a rat-scale value again - the condition resolves itself to
    empty after the first run and stays that way.
    """
    mice = data["Windows"][
        (data["Windows"]["Species"] == "Mouse")
        & (data["Windows"]["Animal Weight Range"].isin(RAT_WEIGHT_RANGES))
    ]
    if mice.empty:
        return False
    new_val = MOUSE_WEIGHT_RANGES[0]
    for idx, row in mice.iterrows():
        old_val = str(row["Animal Weight Range"])
        data["Windows"].at[idx, "Animal Weight Range"] = new_val
        audit_change(data, "Necropsy evidence", row["Window ID"], "Animal Weight Range", old_val, new_val, MOUSE_WEIGHT_RECLASSIFICATION_REASON)
    save_data(data)
    return True


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


def activate_trap(data, trap_id, effective_time, reason, commit=True):
    """Trap activation window brief - mirrors change_trap_build()'s shape:
    a consequential, window-affecting status change gets its own function
    with its own effective-timestamp capture, not folded into the generic
    edit path. Opens exactly one window; there is nothing to close since an
    Inactive trap has none open."""
    idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
    if data["Traps"].at[idx, "Status"] == "Active":
        raise ValueError("Trap is already active.")
    data["Traps"].at[idx, "Status"] = "Active"
    start_window(data, trap_id, effective_time)
    audit_change(data, "Trap", trap_id, "Status", "Inactive", "Active", reason)
    if commit:
        save_data(data)


def deactivate_trap(data, trap_id, effective_time, reason, commit=True):
    """Closes any open window (Review Status: Not required, same as an
    administrative build/move change - this is not a real finding and must
    not spawn a spurious camera-review follow-up) and opens no new window.
    This is the one place activate/deactivate are not mirror images: a
    deactivated trap has nothing to monitor."""
    idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
    if data["Traps"].at[idx, "Status"] == "Inactive":
        raise ValueError("Trap is already inactive.")
    current = open_window(data, trap_id)
    if current is not None:
        widx = data["Windows"].index[data["Windows"]["Window ID"] == current["Window ID"]][0]
        data["Windows"].at[widx, "End Time"] = dtstr(effective_time)
        data["Windows"].at[widx, "Status"] = "Closed"
        data["Windows"].at[widx, "End Reason"] = "Trap deactivated"
        data["Windows"].at[widx, "Review Status"] = "Not required"
    data["Traps"].at[idx, "Status"] = "Inactive"
    audit_change(data, "Trap", trap_id, "Status", "Active", "Inactive", reason)
    if commit:
        save_data(data)


def add_followup(data, followup_type, site_id, trap_id, visit_id, window_id, bag_id, reason, required, priority):
    row = [make_id("FU"), followup_type, site_id, trap_id, visit_id, window_id, bag_id, dtstr(), priority, reason, required, "Open", "", ""]
    data["Followups"] = pd.concat([data["Followups"], pd.DataFrame([row], columns=SHEETS["Followups"])], ignore_index=True)


def sync_workflow_query_params(page: str) -> None:
    """Mirror in-flight workflow context (site/visit/trap) to the URL.

    Additive only: writes these keys while `page` is one of WORKFLOW_PAGES,
    clears them the moment navigation leaves that set. Nothing reads these
    back yet (Phase 2b) — this only keeps the URL in sync so a dropped and
    reconnected session has something to restore from.
    """
    if page in WORKFLOW_PAGES:
        st.query_params[WORKFLOW_QUERY_KEY_PAGE] = page
        for session_key, query_key in WORKFLOW_CONTEXT_QUERY_KEYS.items():
            value = st.session_state.get(session_key)
            if value:
                st.query_params[query_key] = str(value)
    else:
        for query_key in [WORKFLOW_QUERY_KEY_PAGE, *WORKFLOW_CONTEXT_QUERY_KEYS.values()]:
            st.query_params.pop(query_key, None)


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
    sync_workflow_query_params(page)
    if rerun:
        st.rerun()


def clear_workflow_query_params() -> None:
    for query_key in [WORKFLOW_QUERY_KEY_PAGE, *WORKFLOW_CONTEXT_QUERY_KEYS.values()]:
        st.query_params.pop(query_key, None)


def validate_workflow_resume(data, site_id: str, visit_id: str, trap_id: str):
    """Validate a resume candidate read from the URL after a fresh session.

    Every one of these must hold, not a subset: the visit still exists and is
    still open, the trap still exists and its window is still open, and the
    site matches the visit's actual site (guards against a stale or
    manually-edited URL). Returns the visit row on success, None on failure.
    """
    if not (site_id and visit_id and trap_id):
        return None
    visit_rows = data["Visits"][data["Visits"]["Visit ID"] == visit_id]
    if visit_rows.empty:
        return None
    visit_row = visit_rows.iloc[0]
    if visit_row["Status"] != "In progress":
        return None
    if str(visit_row["Site ID"]) != str(site_id):
        return None
    if data["Traps"][data["Traps"]["Trap ID"] == trap_id].empty:
        return None
    if open_window(data, trap_id) is None:
        return None
    return visit_row


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
            // Deliberately not using topAnchor.scrollIntoView() here: the
            // #r1m1-page-top marker sits after the top nav bar in the DOM
            // (app.py places it just below the nav container), so scrolling
            // it to the top of the viewport pushes the nav bar itself off
            // the top of the screen — confirmed by tracing getBoundingClientRect()
            // on the nav during a live navigation, where it measured -65px
            // (fully above the viewport) for the entire ~2s retry window,
            // reproducing the reported "nav bar disappears on every click"
            // symptom exactly. The targets loop below scrolls every actual
            // known scroll container directly to (0,0) with no dependency
            // on any element's position, which is what was needed all along.
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


def connection_status_watcher():
    """Surface Streamlit's own WebSocket connection state as a banner.

    Read-only: observes `data-test-connection-state` and toggles a banner's
    visibility. Never triggers a rerun or touches session_state — Streamlit
    already owns reconnection, this only makes that state visible. Uses a
    distinct element id/flag from scroll_to_top_once (r1m1-page-top /
    scroll_to_top_once key) so the two components can't collide.
    """
    components.html(
        """
        <script>
        (() => {
          const parent = window.parent;
          const doc = parent.document;
          const BANNER_ID = 'r1m1-connection-banner';
          const INSTALL_FLAG = '__r1m1ConnectionWatcherInstalled';

          let banner = doc.getElementById(BANNER_ID);
          if (!banner) {
            banner = doc.createElement('div');
            banner.id = BANNER_ID;
            banner.textContent = 'Connection lost — reconnecting…';
            banner.style.cssText = [
              'position:fixed', 'top:0', 'left:0', 'right:0',
              'z-index:2147483647', 'background:#b91c1c', 'color:#fff',
              'text-align:center', 'padding:8px 12px', 'font-size:14px',
              'font-weight:600', 'display:none'
            ].join(';');
            doc.body.appendChild(banner);
          }

          const sync = () => {
            const stateEl = doc.querySelector('[data-test-connection-state]');
            const state = stateEl ? stateEl.getAttribute('data-test-connection-state') : null;
            banner.style.display = (state && state !== 'CONNECTED') ? 'block' : 'none';
          };

          sync();

          // Only one observer/poll loop should ever run, no matter how many
          // times this component remounts across reruns.
          if (parent[INSTALL_FLAG]) return;
          parent[INSTALL_FLAG] = true;

          const target = doc.querySelector('[data-test-connection-state]');
          if (target) {
            new MutationObserver(sync).observe(target, {
              attributes: true,
              attributeFilter: ['data-test-connection-state'],
            });
          }
          parent.setInterval(sync, 1000);
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


def followup_photo_transaction_context(item) -> dict:
    """Necropsy photo transaction context, keyed by the follow-up's own stable ID.

    A Follow-up ID is already unique and stable the moment the task is
    created (unlike a check, where Visit+Trap isn't unique per attempt —
    that's what deterministic_check_id is for). So the necropsy version can
    reuse the check_id slot directly with the Follow-up ID, no separate
    ID-generation step needed.
    """
    follow_up_id = str(item["Follow-up ID"])
    return {
        "check_id": follow_up_id,
        "follow_up_id": follow_up_id,
        "visit_id": str(item["Visit ID"]),
        "trap_id": str(item["Trap ID"]),
        "site_id": str(item["Site ID"]),
        "bag_id": str(item.get("Bag ID", "") or ""),
        "window_id": str(item["Window ID"]),
    }


def render_photo_capture_widget(context: dict, *, widget_key: str, event_key: str, photo_kind: str = "Check evidence") -> dict:
    """Prepare photos in-browser and persist each selected image before a final save.

    Shared by the check flow and the necropsy follow-up flow: same component,
    same event handling, same manifest calls. Only the context, widget/event
    keys and Photo Type differ between callers — do not fork this into a
    second, simpler photo-upload path for a new caller.
    """
    verification = verify_pending_photo_transaction(DATA_ROOT, context, MAX_SAVED_PHOTO_BYTES)

    component_value = PHOTO_COMPONENT(
        photos=verification.get("photos", []),
        removed_ids=verification.get("removed_ids", []),
        disabled=False,
        retry_delays_ms=[1000, 2000, 4000],
        max_raw_bytes=MAX_RAW_PHOTO_BYTES,
        max_prepared_bytes=MAX_SAVED_PHOTO_BYTES,
        key=widget_key,
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
                        store_pending_photo(DATA_ROOT, context, incoming, MAX_SAVED_PHOTO_BYTES, photo_kind=photo_kind)
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
        "context": context,
        "unresolved_count": unresolved,
    }


def render_check_photo_capture(visit_id: str, trap_id: str, site_id: str, bag_id: str, window_id: str) -> dict:
    """Prepare photos in-browser and persist each selected image before final check save."""
    context = photo_transaction_context(visit_id, trap_id, site_id, bag_id, window_id)
    result = render_photo_capture_widget(
        context,
        widget_key=f"critical_photo_upload_{visit_id}_{trap_id}",
        event_key=photo_component_event_key(visit_id, trap_id),
        photo_kind="Check evidence",
    )
    return {**result, "check_id": context["check_id"]}


def render_followup_photo_capture(item) -> dict:
    """Prepare photos in-browser and persist each selected image before a necropsy save."""
    context = followup_photo_transaction_context(item)
    fid = context["follow_up_id"]
    result = render_photo_capture_widget(
        context,
        widget_key=f"critical_photo_upload_followup_{fid}",
        event_key=f"photo_component_event_followup_{fid}",
        photo_kind="Necropsy evidence",
    )
    return {**result, "follow_up_id": fid}


def correction_necropsy_photo_context(window_id: str, trap_id: str, site_id: str) -> dict:
    """Necropsy photo transaction context for a necropsy entered retroactively via
    Corrections rather than a Necropsy review follow-up task - this happens when a
    kill is confirmed after the fact (e.g. from camera evidence) and no Bag ID was
    ever assigned to queue a normal follow-up task. Deterministic from the Window ID
    alone (like deterministic_check_id), so it survives a browser refresh."""
    follow_up_id = f"CORRNEC-{window_id}"
    return {
        "check_id": follow_up_id,
        "follow_up_id": follow_up_id,
        "visit_id": "",
        "trap_id": str(trap_id),
        "site_id": str(site_id),
        "bag_id": "",
        "window_id": str(window_id),
    }


def render_correction_necropsy_photo_capture(window_id: str, trap_id: str, site_id: str) -> dict:
    """Prepare photos in-browser and persist each selected image before a retroactive
    necropsy correction save."""
    context = correction_necropsy_photo_context(window_id, trap_id, site_id)
    result = render_photo_capture_widget(
        context,
        widget_key=f"critical_photo_upload_corrnec_{window_id}",
        event_key=f"photo_component_event_corrnec_{window_id}",
        photo_kind="Necropsy evidence",
    )
    return {**result, "follow_up_id": context["follow_up_id"]}


def commit_staged_records_with_photos(
    *,
    data: dict,
    staged: dict,
    original_data: dict,
    photo_gate: dict,
    expected_photo_count: int,
    record_id: str,
    photos_id_column: str,
    verify_persisted,
    log_prefix: str,
    log_fields: dict,
    record_noun: str,
    record_description: str,
    session_state_keys_to_clear_on_failure: Optional[list] = None,
) -> int:
    """Finalise photos, append Photos rows, and commit staged sheets with full rollback safety.

    Shared by the check-save and necropsy-save flows so both get the exact
    same checksummed-backup / finalise-then-write / reload-and-verify /
    roll-back-both-or-report-honestly sequence — this is the single place
    that pattern lives, not a copy per flow.

    On success, `data` is updated in place from the reloaded workbook and any
    pending photo transaction is deleted. On failure this calls st.error and
    st.stop() and never returns, matching the pre-extraction check-save flow.
    Because st.stop() halts the script immediately, any caller-side cleanup
    written after this call (e.g. popping a save-in-progress lock) would never
    run on failure - pass session_state_keys_to_clear_on_failure for anything
    that must not survive a failed save, most importantly a save-lock key,
    or the save button stays disabled forever on the next rerun (UX audit,
    2026-08-13).

    verify_persisted(reloaded) is called only after the generic Photos checks
    pass; it must raise RuntimeError with a user-facing reason on failure, or
    return a dict of extra fields to log alongside the commit-verified event.
    """
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
            staged["Photos"][photos_id_column].astype(str) == str(record_id)
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
        persisted_photos = reloaded["Photos"][reloaded["Photos"][photos_id_column].astype(str) == str(record_id)]
        if len(persisted_photos) != expected_photo_count or persisted_photos["Photo ID"].astype(str).nunique() != expected_photo_count:
            raise RuntimeError("The saved workbook did not contain the complete verified photo set.")
        for _, persisted_photo in persisted_photos.iterrows():
            rel = _safe_relative_photo_path(persisted_photo["File Path"])
            path = DATA_ROOT / rel if rel else None
            if path is None or not path.exists() or path.stat().st_size <= 0:
                raise RuntimeError("A saved Photos row did not point to a valid stored file.")

        extra_log_fields = verify_persisted(reloaded) or {}

        log_photo_event(
            DATA_ROOT, f"{log_prefix}_commit_verified",
            expected_count=expected_photo_count, photo_row_count=len(persisted_photos),
            **log_fields, **extra_log_fields,
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
            DATA_ROOT, f"{log_prefix}_commit_failed",
            error=str(exc)[:500], workbook_restored=workbook_restored, files_restored=files_restored,
            rollback_errors=rollback_errors, **log_fields,
        )
        rollback_copy.unlink(missing_ok=True)
        for key in (session_state_keys_to_clear_on_failure or []):
            st.session_state.pop(key, None)
        if rollback_errors or not (workbook_restored and files_restored):
            st.error(f"Save failed and automatic rollback could not be confirmed. Do not continue this {record_noun}; contact the trial lead.")
        else:
            st.error(f"Save failed. No {record_description} was committed. Your selected photos remain available to retry.")
        st.stop()
    finally:
        rollback_copy.unlink(missing_ok=True)

    if expected_photo_count:
        delete_transaction(DATA_ROOT, record_id)

    return len(saved_photo_files)


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


def recreate_followup(data, window_id: str, followup_type: str, reason: str):
    """Recreate a Camera review or Necropsy review follow-up for a window whose Review
    Status shows 'Needs recreation' - the only path back once a genuinely-warranted task
    has been removed (or otherwise lost). Wraps add_followup rather than duplicating it,
    so a recreated task behaves identically to a normally-created one."""
    if not reason.strip():
        raise ValueError("Enter a reason for recreating the follow-up.")
    matches = data["Windows"][data["Windows"]["Window ID"] == window_id]
    if matches.empty:
        raise ValueError("Window not found.")
    w = matches.iloc[0]
    existing = data["Followups"][
        (data["Followups"]["Window ID"] == window_id)
        & (data["Followups"]["Follow-up Type"] == followup_type)
        & (data["Followups"]["Status"] == "Open")
    ]
    if not existing.empty:
        raise ValueError("An open follow-up of this type already exists for this window.")
    staged = {name: frame.copy(deep=True) for name, frame in data.items()}
    add_followup(
        staged, followup_type, w["Site ID"], w["Trap ID"], w.get("Visit ID", ""),
        window_id, w.get("Bag ID", ""), w["Finding At Close"],
        "Recreated after prior removal — see Audit Log for original removal reason.",
        "Normal",
    )
    refresh_review_status(staged, window_id)
    audit_change(staged, "Follow-up", window_id, "Recreated", "", followup_type, reason.strip())
    save_data(staged)
    for name in data:
        data[name] = staged[name]
    return followup_type


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


def necropsy_consistency_errors(status: str, assessment: str, final: str) -> list:
    """Cross-field consistency rules for a necropsy result. Shared by the
    original Necropsy review task and the Necropsy evidence correction tool
    so a correction can't silently save data the first-entry flow would have
    rejected (UX audit, 2026-08-13 - the correction form previously had no
    equivalent of these checks at all)."""
    errors = []
    if status == "Complete" and assessment == "Not assessable":
        errors.append("A completed necropsy cannot be marked Not assessable.")
    if assessment == "Supports humane kill" and final != "Yes":
        errors.append("A supportive necropsy must have a final humane-kill result of Yes.")
    if assessment == "Does not support humane kill" and final != "No":
        errors.append("A non-supportive necropsy must have a final humane-kill result of No.")
    if status in ["Not completed", "Unable to assess"] and final in ["Yes", "No"]:
        errors.append("Do not record a definite final result when the necropsy was not completed or assessable.")
    return errors


def physical_kill_population(windows: pd.DataFrame) -> pd.DataFrame:
    return windows[windows["Finding At Close"] == "Dead animal found"].copy()


# Time-to-kill target per Project Brief (2025), Craig Bond (Chief Product).
# Confirmed as the correct, current target by Jacob Sheehan, 12 Aug 2026.
TIME_TO_KILL_TARGET_MINUTES = 24*60
TIME_TO_KILL_TARGET_SOURCE = "Project Brief (2025), Craig Bond (Chief Product) - confirmed by Jacob Sheehan, 12 Aug 2026"
TIME_TO_KILL_TARGET_SET_DATE = "2026-08-12"


def _derived_sheet_data(data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Compute the read-only Trial Config and Kills sheets from current data.

    Documentation written from the code constant / Windows data, never a
    second source of truth - there is no UI path that writes to either
    sheet. Called from inside save_data() itself, not left to individual
    call sites, since there are many save_data() call sites throughout the
    app and missing even one would silently leave a stale or blank sheet.
    """
    trial_config = pd.DataFrame(
        [["Time to kill target (minutes)", str(TIME_TO_KILL_TARGET_MINUTES), TIME_TO_KILL_TARGET_SOURCE, TIME_TO_KILL_TARGET_SET_DATE]],
        columns=SHEETS["Trial Config"],
    )

    windows = data.get("Windows", blank("Windows"))
    kills = physical_kill_population(windows)
    kills_cols = SHEETS["Kills"]
    kills_out = kills[kills_cols].copy() if not kills.empty else blank("Kills")

    return {"Trial Config": trial_config, "Kills": kills_out}

DATA_QUALITY_REVIEW_RECORD_TYPE = "Data quality review"

# Derived from real completed-visit check-activity spans, confirmed 11 Aug 2026.
# Of 8 completed visits, only 4 were confirmed genuine single continuous
# site checks (0 to 34.3 min of check-to-check span); the other 2 (5.15 hr,
# 10.94 hr) were confirmed NOT real continuous visits - a Visit record left
# open and resumed later under the same Visit ID, not one accelerated check -
# and excluded from this derivation. VIS-TR-20260806-224548-9542 (34.3 min,
# 9 checks) is the longest confirmed-real span. Set to roughly 2.6x that, so
# a real visit is never mistaken for isolation with a comfortable margin.
# Revisit once more completed-visit data exists to derive this with a larger
# sample than n=4.
DATA_QUALITY_ISOLATION_WINDOW_MINUTES = 90


def data_quality_reviewed_check_ids(data: Dict[str, pd.DataFrame]) -> set:
    """Check IDs already reviewed (confirmed real or voided) - a human decision
    is permanent once made, so a confirmed check must never resurface as a
    candidate again. Tracked via Audit Log rather than a field on the Check
    row itself: confirming a check as real makes no data change, so there is
    nothing else to check for on the row - the log is the only durable record
    that the review happened at all."""
    log = data["Audit Log"]
    if log.empty:
        return set()
    return set(log[log["Record Type"] == DATA_QUALITY_REVIEW_RECORD_TYPE]["Record ID"].astype(str))


def find_data_quality_candidates(data: Dict[str, pd.DataFrame], window_minutes: int = DATA_QUALITY_ISOLATION_WINDOW_MINUTES) -> list:
    """Flag checks with no other trap activity nearby at the same site.

    Isolation, not duration, is the signal: a real accelerated whole-line
    check (site operators deliberately check every trap on a site ahead of
    schedule whenever a kill is found anywhere on it) always shows multiple
    traps checked together, clustered close in time. A single trap checked
    alone, with nothing else at that site nearby, is the actual tell - a
    short resulting window is common and legitimate on its own and is
    deliberately not used as a signal here.
    """
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


def void_check_as_test_data(data: Dict[str, pd.DataFrame], check_id: str, reason: str) -> None:
    """Soft-exclude a check confirmed to be test/UI data, and the window it
    closed (whose Finding/Species/etc. feed Trial Performance directly) -
    never a hard delete. The window boundary itself (this check possibly also
    opening a new window) is left exactly as-is, a deliberate, confirmed
    choice: the split happened, and unwinding it risks orphaning any
    Followups/Photos row that already references the new window's ID."""
    if not reason.strip():
        raise ValueError("Enter a reason for voiding this record.")
    check_idxs = data["Checks"].index[data["Checks"]["Check ID"].astype(str) == str(check_id)].tolist()
    if not check_idxs:
        raise ValueError("That check could not be found.")
    check_idx = check_idxs[0]
    reason = reason.strip()

    data["Checks"].at[check_idx, "Excluded"] = "Yes"
    data["Checks"].at[check_idx, "Exclusion Reason"] = reason
    audit_change(data, "Check", check_id, "Excluded", "", "Yes", reason)

    window_id = str(data["Checks"].at[check_idx, "Window Closed"] or "")
    if window_id:
        window_idxs = data["Windows"].index[data["Windows"]["Window ID"] == window_id].tolist()
        if window_idxs:
            window_idx = window_idxs[0]
            data["Windows"].at[window_idx, "Excluded"] = "Yes"
            data["Windows"].at[window_idx, "Exclusion Reason"] = reason
            audit_change(data, "Window", window_id, "Excluded", "", "Yes", reason)

    save_data(data)


def confirm_check_as_real(data: Dict[str, pd.DataFrame], check_id: str) -> None:
    """Record a human's confirmation that a flagged check is real field data.
    Makes no change to the check or window's recorded values - the Audit Log
    entry alone is what keeps this candidate from resurfacing."""
    if data["Checks"][data["Checks"]["Check ID"].astype(str) == str(check_id)].empty:
        raise ValueError("That check could not be found.")
    audit_change(data, DATA_QUALITY_REVIEW_RECORD_TYPE, check_id, "Review", "", "Confirmed real", "Reviewed and confirmed as real field data, not test data.")
    save_data(data)


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


def suspect_earliest_window_candidates(data: Dict[str, pd.DataFrame], product: str) -> list:
    """Flag traps of the given product whose earliest window's Start Time falls
    on a different calendar day than the trap's own Deployment Start.

    This is the exact signature the "trap was physically live before being
    added to the app" bug leaves behind: start_window() stamps Start Time
    with whatever moment the trap record was entered, while Deployment Start
    (edited separately) holds the operator's belief about the true date.
    A day-level mismatch between the two is real, code-grounded evidence of
    the bug — not a guess about "looks like batch entry."
    """
    candidates = []
    traps = data["Traps"][data["Traps"]["Product"] == product]
    for _, t in traps.iterrows():
        trap_id = t["Trap ID"]
        windows = data["Windows"][data["Windows"]["Trap ID"] == trap_id].copy()
        if windows.empty:
            continue
        windows["_start_dt"] = windows["Start Time"].apply(parse_dt)
        windows = windows[windows["_start_dt"].notna()]
        if windows.empty:
            continue
        earliest = windows.sort_values("_start_dt").iloc[0]
        window_start_dt = earliest["_start_dt"]
        deployment_dt = parse_dt(t["Deployment Start"])
        suspect = deployment_dt is None or window_start_dt.date() != deployment_dt.date()
        if not suspect:
            continue
        candidates.append({
            "Trap ID": trap_id,
            "Site ID": t["Site ID"],
            "Window ID": earliest["Window ID"],
            "Current Start": window_start_dt,
            "Deployment Start": deployment_dt,
            "Review Status": str(earliest["Review Status"]),
            "Eligible": str(earliest["Review Status"]) != "Complete",
        })
    return candidates


def correct_window_start(data: Dict[str, pd.DataFrame], window_id: str, new_start: datetime, reason: str) -> bool:
    """Correct a single window's Start Time, re-checking eligibility against
    live data (not a page-render-time snapshot) so a review completed after
    the diagnostic list was drawn can never be silently overwritten."""
    idxs = data["Windows"].index[data["Windows"]["Window ID"] == window_id].tolist()
    if not idxs:
        raise ValueError(f"Window {window_id} could not be found.")
    idx = idxs[0]
    if str(data["Windows"].at[idx, "Review Status"]) == "Complete":
        raise ValueError("This window's review has already been completed and can no longer be corrected here.")
    old_value = str(data["Windows"].at[idx, "Start Time"])
    new_value = dtstr(new_start)
    if old_value == new_value:
        return False
    data["Windows"].at[idx, "Start Time"] = new_value
    recalculate_window(data, idx)
    audit_change(data, "Window", window_id, "Start Time", old_value, new_value, reason)
    return True


@contextmanager
def app_card():
    """A bordered Streamlit container with an app-owned marker for reliable styling."""
    with st.container(border=True):
        st.markdown(
            '<span class="app-card-marker" aria-hidden="true"></span>',
            unsafe_allow_html=True,
        )
        yield


def status_pill(label: str, kind: str = "none") -> str:
    """Shared status indicator markup: a pale-background pill for a state
    worth drawing the eye to (kind in "success"/"guidance"/"warning"), or
    plain muted text when kind == "none" — a background fact (e.g.
    Inactive) that's deliberately not meant to visually compete with the
    states that are. Returns HTML; callers compose it into their own
    st.markdown call rather than this rendering directly, so it works both
    standalone and inside render_compact_card_content below."""
    if not label:
        return ""
    if kind == "none":
        return f'<span class="shared-card-label">{html.escape(str(label))}</span>'
    return f'<span class="status-pill status-pill-{html.escape(str(kind))}">{html.escape(str(label))}</span>'


def coequal_stats(stats) -> None:
    """Trial performance brief Phase 2 (2d) — two primary values shown at
    identical size/weight, side by side, neither promoted over the other.
    stats: iterable of (value, label, kind) where kind is "" or "success"."""
    parts = []
    for value, label, kind in stats:
        value_class = f"coequal-value {kind}".strip()
        parts.append(
            f'<div class="coequal-stat"><div class="{value_class}">{html.escape(str(value))}</div>'
            f'<div class="coequal-label">{html.escape(str(label))}</div></div>'
        )
    st.markdown(f'<div class="coequal-row">{"".join(parts)}</div>', unsafe_allow_html=True)


def action_callout(message_html: str) -> None:
    """Amber actionable-pointer callout (Trial performance brief 2d) — the
    same visual treatment as the funnel's Main loss box, reserved for a
    pointer at unfinished work, not passive methodology text (that's
    card_footer below)."""
    st.markdown(f'<div class="action-callout">{message_html}</div>', unsafe_allow_html=True)


def card_footer(label: str, tooltip_html: str, *, wide: bool = False) -> None:
    """Passive, tooltip-gated methodology/coverage context (Trial performance
    brief 2g) — a short label + (i) icon, full detail on hover, tap, or
    keyboard focus. Deliberately not a Streamlit help= tooltip: that's
    hover-only, and this app has real mobile/field usage elsewhere, so
    hover-only would silently break on touch devices. The tap path needs
    install_grey_footer_tooltips() called once on the page; the keyboard
    path needs no JS at all — :focus alone shows the tooltip via CSS,
    since the icon carries tabindex="0"."""
    wide_class = " wide" if wide else ""
    st.markdown(
        f'<div class="card-footer">{html.escape(label)}'
        f'<span class="info-icon" tabindex="0">i</span>'
        f'<span class="tooltip{wide_class}">{tooltip_html}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def install_grey_footer_tooltips() -> None:
    """Tap-to-toggle behaviour for card_footer's info-icon/tooltip, for touch
    devices where there's no true hover state. Hover and keyboard focus
    already work via pure CSS (see .info-icon rules) with no JS at all.

    One delegated click listener on the parent document, installed once and
    guarded the same way as connection_status_watcher — event delegation
    means it keeps working across every Streamlit rerun without needing to
    re-attach per icon each time this markup re-renders."""
    components.html(
        """
        <script>
        (() => {
          const parent = window.parent;
          const doc = parent.document;
          const INSTALL_FLAG = '__r1m1FooterTooltipsInstalled';
          if (parent[INSTALL_FLAG]) return;
          parent[INSTALL_FLAG] = true;

          doc.addEventListener('click', (e) => {
            const icon = e.target.closest('.info-icon');
            const open = doc.querySelectorAll('.info-icon.tap-active');
            const wasActive = icon && icon.classList.contains('tap-active');
            open.forEach((el) => el.classList.remove('tap-active'));
            if (icon && !wasActive) icon.classList.add('tap-active');
          });
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def site_urgency_pill(next_due_date, today_date) -> tuple[str, str]:
    """Relative-urgency pill for a site not yet visited this cycle.

    Takes plain date objects (not datetime) so the boundary math is exact
    calendar-day comparison, not a 24-hour window — "Due today" means the
    next-due date is today's calendar date, regardless of what time it is
    right now.

    Returns (status_text, status_kind) for status_pill(). ("", "none")
    means show no pill — the site isn't due soon enough to flag; card-system
    brief Phase 2 deliberately doesn't define a lookahead window, so
    anything due in the future (even tomorrow) is quiet, matching the
    existing "Inactive" restraint principle elsewhere in the pill system.
    """
    days_until_due = (next_due_date - today_date).days
    if days_until_due < 0:
        overdue_days = -days_until_due
        return f"Overdue by {overdue_days} day{'s' if overdue_days != 1 else ''}", "error"
    if days_until_due == 0:
        return "Due today", "warning"
    return "", "none"


def render_compact_card_content(
    *,
    title: str,
    right_label: str = "",
    right_label_kind: Optional[str] = None,
    main_line: str = "",
    meta_line: str = "",
    meta_line_2: str = "",
) -> None:
    """Render the shared compact card hierarchy without relying on Streamlit wrappers."""
    if right_label_kind is not None:
        right_html = status_pill(right_label, right_label_kind)
    else:
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
    meta_html_2 = (
        f'<div class="shared-card-meta">{html.escape(str(meta_line_2))}</div>'
        if meta_line_2 else ""
    )
    st.markdown(
        '<div class="shared-card-copy">'
        '<div class="shared-card-heading">'
        f'<strong>{html.escape(str(title))}</strong>{right_html}'
        '</div>'
        f'{main_html}{meta_html}{meta_html_2}'
        '</div>',
        unsafe_allow_html=True,
    )


def render_visit_trap_card(tr, checked: bool, visit_id: str, site_id: str) -> None:
    """Compact field card with one checked-state indicator."""
    trap_id = str(tr["Trap ID"])
    build_prefix = f"{tr['Product']} Build "
    build_raw = str(tr["Build Version"] or "—")
    build_text = build_raw[len(build_prefix):] if build_raw.startswith(build_prefix) else build_raw
    product_build = f"Build: {build_text}"
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


def header(title, subtitle="", *, emphasize_subtitle=False):
    """emphasize_subtitle: Trial performance brief 2c — that page's subtitle
    reframes toward the question the page answers and needs more visual
    weight against its H1/cards than the shared .page-context style gives
    every other page's subtitle. Opt-in per call site, not a global change
    to .page-context, since no other page asked for this."""
    st.title(title)
    if subtitle:
        subtitle_class = "page-context page-context-emphasis" if emphasize_subtitle else "page-context"
        st.markdown(f'<p class="{subtitle_class}">{subtitle}</p>', unsafe_allow_html=True)


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
st.markdown(
    """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
""",
    unsafe_allow_html=True,
)
st.markdown("""
<style>

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

/* Buttons. Descendant (not direct-child) selectors deliberately: a button
   with a help= tooltip gets wrapped by Streamlit in extra
   stTooltipHoverTarget/stTooltipIcon spans between div.stButton and the
   actual <button>, which silently broke "div.stButton > button" for any
   button with a tooltip (confirmed via devtools on "Finish site check" —
   it kept the radius from a separate, non-child-restricted rule, but fell
   back to Streamlit's raw 4px/12px padding and 40px min-height here). */
div.stButton button,
div.stFormSubmitButton button,
div.stDownloadButton button {
  border-radius: 999px;
  font-family: 'Inter', sans-serif;
  font-weight: 700;
  min-height: 2.75rem;
  padding-left: 1.15rem;
  padding-right: 1.15rem;
}
button[kind="primary"],
[data-testid="stBaseButton-primary"] {
  background: var(--brand-orange) !important;
  border-color: var(--brand-orange) !important;
  color: #ffffff !important;
  border-radius: 999px !important;
}
button[kind="primary"] *,
[data-testid="stBaseButton-primary"] * {color: #ffffff !important;}
/* Disabled primary buttons must look disabled — without this, the
   unconditional !important above painted a disabled button in the exact
   same full-strength orange as an active one, with only cursor:not-allowed
   (meaningless on a touchscreen) distinguishing them. Confirmed via
   getComputedStyle on a real disabled "Finish site check" button:
   background/opacity/color all read identical to enabled. */
button[kind="primary"]:disabled,
[data-testid="stBaseButton-primary"]:disabled {
  opacity: .45 !important;
  cursor: not-allowed !important;
}
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
[data-testid="stForm"] div.stFormSubmitButton button {width: auto;}
.element-container:has(div.stButton),
.element-container:has(div.stFormSubmitButton) {margin-top: .35rem;}

/* App-owned marked cards plus Streamlit wrapper fallback. */
.app-card-marker {display: none !important;}
/* site-complete-marker (a second, separate hidden hook span used only on a
   freshly-completed site's card - see the "sites" page) has the exact same
   issue below, so it gets the same two-part fix. Confirmed live on staging:
   a completed-today card showed 32px of dead space (two phantom gaps
   stacked) where a normal card only had one, because this marker's own
   container wasn't covered by the app-card-marker fix - local demo data
   never exercised a "completed today" card during testing, so this half
   was missed the first time. */
.site-complete-marker {display: none !important;}
/* The marker spans above are hidden, but their own stElementContainer divs
   aren't - those divs still count as flex siblings in the card's column
   layout, so the card's inter-element gap (16px, Streamlit's own default)
   still opens up around them even though they render at 0 height. That
   reads as unexplained dead space above every card's title (padding plus
   a phantom gap per hidden marker present) - confirmed via getComputedStyle
   showing 0-height children still consuming a gap. Hiding the whole
   container removes each one from the flex layout entirely. */
[data-testid="stElementContainer"]:has(.app-card-marker),
[data-testid="stElementContainer"]:has(.site-complete-marker) {display: none !important;}

/* Same bug, page-chrome scale: HEADER_PADDING_BRIEF.md was written against
   a screenshot of a large empty region above the top nav, and traced that
   to six competing padding-top rules. Real measurement found the padding
   rules were a minor factor - the actual dominant cause was five separate
   invisible elements at the very top of the page (Google-Fonts preconnect
   links, two pure-CSS <style> blocks, and two components.html() scripts -
   the light-theme-forcing script and the connectivity banner) each still
   counting as a flex sibling in the page's own top-level column layout and
   each still eating a full 16px gap despite rendering at 0 height. Five of
   them stacked to 80px of pure phantom space before the nav pills even
   start - confirmed live by disabling them one at a time and watching the
   nav's rendered top position drop by exactly 16px each time.
   Scoped to only the page's own outermost stVerticalBlock's direct
   children (not a bare [data-testid="stElementContainer"] selector) so
   this can never reach into a card or a page's own content further down
   the tree - verified a <style> tag's rules still apply and an iframe's
   script still runs with its container hidden this way (this is standard
   platform behaviour: neither depends on an ancestor's CSS display), by
   toggling this rule on a live page and confirming fonts/brand colours/
   color-scheme were byte-identical before and after. */
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has(> .stMarkdown [data-testid="stMarkdownContainer"] > link),
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has(> .stMarkdown [data-testid="stMarkdownContainer"] > style),
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has(> iframe[data-testid="stIFrame"]),
/* Same phantom-gap fix, scoped to a popover body instead of the page's own
   top-level block - needed the moment a popover renders its own conditional
   style-only markdown (Administration's Data quality badge), since a
   popover's content sits in a different container than stMainBlockContainer
   and the rule above never reaches it. */
[data-testid="stPopoverBody"] [data-testid="stElementContainer"]:has(> .stMarkdown [data-testid="stMarkdownContainer"] > style) {
  display: none !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker),
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .app-card-marker),
div[data-testid="stVerticalBlock"]:has(> div.element-container .app-card-marker) {
  background: var(--panel) !important;
  border: 1px solid var(--line) !important;
  box-shadow: 0 0 0 1px rgba(0,0,0,.05), 0 0 20px rgba(0,0,0,.05), 0 0 100px rgba(0,0,0,.05) !important;
  border-radius: 20px !important;
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

  div.stButton button,
  div.stFormSubmitButton button,
  div.stDownloadButton button {
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

/* Section cards: one clear boundary, no heavy nesting. */
[data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker),
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .app-card-marker),
div[data-testid="stVerticalBlock"]:has(> div.element-container .app-card-marker) {
  background: var(--panel) !important;
  border: 1px solid var(--line) !important;
  border-radius: 20px !important;
  box-shadow: 0 0 0 1px rgba(0,0,0,.05), 0 0 20px rgba(0,0,0,.05), 0 0 100px rgba(0,0,0,.05) !important;
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
  div.stButton button,
  div.stFormSubmitButton button,
  div.stDownloadButton button {
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
div[data-testid="stHorizontalBlock"]:has(.drawer-close-marker) div.stButton button { min-height: 2.25rem !important; height: 2.25rem !important; width: 2.25rem !important; padding: 0 !important; border-radius: 999px !important; font-size: 1.35rem !important; line-height: 1 !important; background: transparent !important; border-color: transparent !important; color: var(--muted) !important; box-shadow: none !important; }
div[data-testid="stHorizontalBlock"]:has(.drawer-close-marker) div.stButton button:hover { background: #ececea !important; color: var(--text) !important; }
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

/* Keep page-level navigation and context below Streamlit's mobile header.
   The block-container padding-top rule that used to live here was dead
   code - confirmed by disabling it live and finding computed padding-top
   unchanged - because [data-testid="stMainBlockContainer"] (the
   "authoritative page rhythm" rule further down this file) always wins
   the cascade regardless: higher specificity from its
   body:not(:has(.login-page-marker)) guard beats a bare .block-container
   selector even with !important on both sides. Removed as part of the
   header-padding consolidation (HEADER_PADDING_BRIEF.md) rather than left
   as dead weight. Header min-height stays - a real, live rule - but moved
   from 768px to 700px in that same pass: once the phantom flex-gap fix
   below removes the "accidental cushion" that used to quietly absorb the
   701-768px mismatch between this rule's old breakpoint and every other
   mobile rule's 700px, that mismatch becomes a real 8px header/content
   overlap in that range (confirmed live) instead of an invisible one. */
@media (max-width: 700px) {
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
  border-radius: 20px;
  box-shadow: 0 0 0 1px rgba(0,0,0,.05), 0 0 20px rgba(0,0,0,.05), 0 0 100px rgba(0,0,0,.05);
  background: #ffffff;
  box-sizing: border-box;
}
.visit-trap-card.is-checked {
  background: #eef8f1;
  border-color: #b9ddc5;
}
.visit-trap-meta { color: var(--muted); margin-top: .35rem; }
.visit-trap-status { color: #22683d; font-weight: 700; margin-top: .35rem; }
@media (max-width: 700px) {
  .visit-trap-card {
    grid-template-columns: minmax(7.5rem, 1fr) minmax(8rem, 1.35fr) 2.5rem;
    min-height: 6.4rem;
    gap: .7rem;
    padding: .9rem;
  }
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
  border-radius: 20px !important;
  box-shadow: 0 0 0 1px rgba(0,0,0,.05), 0 0 20px rgba(0,0,0,.05), 0 0 100px rgba(0,0,0,.05) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker) > div,
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) > div {
  padding: 15px !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.site-complete-marker),
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .site-complete-marker),
div[data-testid="stVerticalBlock"]:has(> div.element-container .site-complete-marker) {
  background: var(--card-success-bg) !important;
  border-color: var(--card-success-border) !important;
}

.shared-card-copy { display:grid; gap:15px; width:100%; margin:0 0 .35rem 0; }
.shared-card-heading { display:flex; justify-content:space-between; align-items:baseline; gap:.75rem; }
.shared-card-heading strong { color:var(--text); font-size:22px; }
.shared-card-main { color:var(--text); font-size:.95rem; }
.shared-card-meta { color:var(--muted); font-size:.86rem; line-height:1.4; }
.shared-card-label { color:var(--text); font-size:.88rem; text-align:right; }

/* Field cards use the same neutral base and identical geometry between states. */
.visit-trap-card,
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) {
  background:var(--card-bg) !important;
}
.visit-trap-card.is-checked {
  background:var(--card-success-bg) !important;
  border-color:var(--card-success-border) !important;
}
.visit-trap-card { padding:15px !important; margin-bottom:.7rem !important; min-height:0 !important; }

/* Compact action spacing inside all shared cards. */
[data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker) .stButton,
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) .stButton {
  margin-top:15px !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker) .stButton button,
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) .stButton button {
  min-height:2.7rem !important;
}/* Exactly one app-owned drawer-close chevron. Hide every native drawing layer. */

@media (max-width:700px) {
  [data-testid="stVerticalBlockBorderWrapper"]:has(.app-card-marker) > div,
  [data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) > div,
  .visit-trap-card { padding:15px !important; }
  .shared-card-heading { gap:.5rem; }
  .shared-card-main { font-size:.9rem; }
  .shared-card-meta, .shared-card-label { font-size:.82rem; }
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
.visit-trap-card { min-height:0 !important; padding:15px !important; display:block !important; margin-bottom:.7rem !important; }
.visit-trap-copy { display:grid; gap:.35rem; width:100%; }
.visit-trap-line { display:flex; justify-content:space-between; align-items:baseline; gap:1rem; }
.visit-trap-meta { color:#737780; font-size:.9rem; }
.visit-trap-status { color:#22683d; white-space:nowrap; }
.visit-trap-card.is-checked { background:#eef8f1 !important; border-color:#b9ddc5 !important; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) { margin-bottom:.7rem !important; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) > div { padding:15px !important; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) .stButton button { min-height:2.7rem !important; margin-top:.45rem !important; }

/* Completed site state and compact site metadata. */
[data-testid="stVerticalBlockBorderWrapper"]:has(.site-complete-marker),
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .site-complete-marker),
div[data-testid="stVerticalBlock"]:has(> div.element-container .site-complete-marker) { background:#eef8f1 !important; border-color:#b9ddc5 !important; }
.site-card-compact { display:grid; gap:.35rem; }
.site-card-heading { display:flex; justify-content:space-between; gap:1rem; align-items:baseline; font-size:22px; }
.site-card-meta { color:#737780; font-size:.9rem; }

/* v8.7.6.6 photo layout is isolated inside the custom component iframe. */

@media (max-width:700px) {
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
  border-radius:20px !important;
  box-shadow: 0 0 0 1px rgba(0,0,0,.05), 0 0 20px rgba(0,0,0,.05), 0 0 100px rgba(0,0,0,.05) !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.setup-trap-card-marker) > div,
[data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) > div {
  padding:15px !important;
}

/* Streamlit wrapper fallback for mobile DOM variants. Keep the selector limited to
   a bordered block containing one of the two page-specific markers. */
div[data-testid="stVerticalBlock"]:has(.setup-trap-card-marker)[style*="border"],
div[data-testid="stVerticalBlock"]:has(.visit-unchecked-marker)[style*="border"] {
  background:#f3f3f0 !important;
  border-color:#d7d9dd !important;
  border-radius:20px !important;
  box-shadow: 0 0 0 1px rgba(0,0,0,.05), 0 0 20px rgba(0,0,0,.05), 0 0 100px rgba(0,0,0,.05) !important;
}

@media (max-width:700px) {
  [data-testid="stVerticalBlockBorderWrapper"]:has(.setup-trap-card-marker),
  [data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) {
    margin-bottom:.7rem !important;
  }
  [data-testid="stVerticalBlockBorderWrapper"]:has(.setup-trap-card-marker) > div,
  [data-testid="stVerticalBlockBorderWrapper"]:has(.visit-unchecked-marker) > div {
    padding:15px !important;
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
   Keep only normal Streamlit-header and menu-control clearance.

   As of HEADER_PADDING_BRIEF.md, this pair is the ONLY padding-top rule
   for this element in the whole file - five other declarations (four on
   the plain .block-container class, one duplicate of this same selector)
   used to compete for the same property. All five were confirmed dead by
   directly disabling them live and checking computed padding-top didn't
   move: this selector's specificity (a body:not(:has()) guard plus an
   attribute selector) beats a bare class selector even when both sides
   carry !important, so this rule has always won regardless of source
   order.

   Values recalibrated in the same pass, not left at their old numbers:
   the real driver of the large gap the brief was written to fix wasn't
   these two rules at all, it was five separate invisible top-of-page
   elements (font-preconnect links, two big <style> blocks, and two
   components.html() scripts) each still eating a full 16px flex-gap
   despite rendering at 0 height - 80px of pure phantom space, fixed
   below by hiding their containers outright. But that phantom space had
   been accidentally covering for these two values being too small to
   clear the header on their own (52px/60px padding against a 60px/68px
   header) - removing it without raising these would have clipped content
   under the header by 8px, confirmed live before adjusting. New values:
   header height (60px above 700px, 68px at or below, both now on the
   same 700px breakpoint as the header's own min-height rule instead of
   the old mismatched 768px) plus a flat 12px margin. Total clearance
   confirmed at 72px (>700px) and 80px (<=700px) live, at every width
   tested including the former 701-768px mismatch zone. */
body:not(:has(.login-page-marker)) [data-testid="stMainBlockContainer"] {
  padding-top:4.5rem !important;
}

@media (max-width:700px) {
  body:not(:has(.login-page-marker)) [data-testid="stMainBlockContainer"] {
    padding-top:calc(5rem + env(safe-area-inset-top)) !important;
  }
}
</style>

<style>
/* v8.7.6.4 — one responsive navigation flow */
.st-key-app_top_navigation {
  width: 100%;
}

/* No space before [data-testid] deliberately: stHorizontalBlock is a
   data-testid on .st-key-app_top_navigation itself, not a descendant of
   it — the previous descendant-combinator selector here could never match
   anything (confirmed via devtools: zero matched rules), so this row was
   silently running on Streamlit's own default 1rem gap the whole time.
   That extra width was enough to overflow the row at normal desktop
   widths, forcing Administration onto its own second line — which is what
   was actually behind the "Administration sits lower" symptom, not a
   same-row height mismatch between stPageLink and stPopover. */
.st-key-app_top_navigation[data-testid="stHorizontalBlock"] {
  width: 100%;
  flex-wrap: wrap !important;
  align-items: center !important;
  column-gap: .4rem !important;
  row-gap: .42rem !important;
}

/* [data-testid="stPopoverButton"] here, not "[stPopover] > button": the
   real button sits behind an extra unnamed wrapper div (stPopover > div >
   button), so the old "> button" direct-child selector never matched
   anything either (confirmed via devtools — zero matched rules, same
   failure mode as the stHorizontalBlock gap selector above). The
   Administration pill's visible styling up to now came entirely from
   broader app-wide button rules, not from this nav-specific block, which
   is why its padding/height never quite matched its siblings. */
.st-key-app_top_navigation [data-testid="stPageLink"] a,
.st-key-app_top_navigation [data-testid="stPopoverButton"] {
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
.st-key-app_top_navigation [data-testid="stPopoverButton"] * {
  color: #25262d !important;
}

.st-key-app_top_navigation [data-testid="stPageLink"] a:hover,
.st-key-app_top_navigation [data-testid="stPopoverButton"]:hover {
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
  .st-key-app_top_navigation[data-testid="stHorizontalBlock"] {
    column-gap: .32rem !important;
    row-gap: .38rem !important;
  }

  .st-key-app_top_navigation [data-testid="stPageLink"] a,
  .st-key-app_top_navigation [data-testid="stPopoverButton"] {
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
  border: none !important;
  border-radius: 10px !important;
  box-shadow: 0 0 0 1px rgba(0,0,0,.05), 0 0 20px rgba(0,0,0,.05), 0 0 100px rgba(0,0,0,.05) !important;
}
[data-testid="stPopoverBody"] * {
  color: #25262d !important;
}
[data-testid="stPopoverBody"] button[kind="secondary"],
[data-testid="stPopoverBody"] [data-testid="stBaseButton-secondary"] {
  background: #ffffff !important;
  border-color: #d7d9dd !important;
}

/* Card-system brief: bring the popover's page-link/button rows to the same
   40px/15px row rhythm as the rest of this release, in place of whatever
   height/padding they happened to inherit from the generic button rules. */
[data-testid="stPopoverBody"] [data-testid="stPageLink"] a {
  min-height: 40px !important;
  padding: 0 15px !important;
  display: flex !important;
  align-items: center !important;
}
[data-testid="stPopoverBody"] div.stButton button {
  min-height: 40px !important;
  padding: 0 15px !important;
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

<style>
/* UI polish: desktop card width cap. This container already had a plain
   (non-!important) max-width:1220px via .block-container, which still left
   cards visibly bunched left with a large empty gap on a real desktop
   screen. First tried 760px, matching the original design review — but
   verification against the actual Trial performance page found 5 of 9
   st.metric labels (both the "Performance at a glance" stat row and the
   Camera conversion funnel breakdown) truncate with an ellipsis at that
   width, since column width there is a further 2-3-way division of
   whatever this container measures. 1020px is the point where all of them
   fit without truncating, checked directly against rendered label
   scrollWidth/clientWidth, while still meaningfully narrower than 1220px.
   The funnel's narrowest label sits in a 1.2-of-5 column split, so it
   needs a disproportionate amount of overall width increase to close a
   small pixel gap — don't assume a round number like 960 or 1000 is
   enough without re-measuring scrollWidth/clientWidth directly.
   Scoped with the same body:not(:has(.login-page-marker)) guard the
   existing "authoritative page rhythm" padding-top rule already uses, to
   avoid an !important-vs-!important fight with the login page's own
   max-width:30rem rule on this same selector. min-width:701px (not just
   applying unconditionally) so this can never compete with the existing
   @media (max-width:700px) card-padding rule below — mobile must render
   identically to before this change. */
@media (min-width: 701px) {
  body:not(:has(.login-page-marker)) [data-testid="stMainBlockContainer"] {
    max-width: 1020px !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }

  /* Card padding/gap/button spacing intentionally not overridden here any
     more — the card-system brief moved these to one consistent 15px value
     (outer padding, inter-element gap, and button spacing alike) at every
     breakpoint, so the desktop-only "loosen it further" step this block
     used to do is now redundant with the base rules above. */
}
</style>

<style>
/* UI polish: shared status_pill() treatment. Card status labels (Active,
   Current, In progress, Ready to finish, Last checked today) previously
   rendered as page-specific bare coloured/black text with no shared
   component, which is how the inconsistency drifted in the first place.
   Applies at every width — unlike the card max-width/spacing block above,
   there's no reason a pill needs to be desktop-only, and the bare-text
   inconsistency was confirmed at mobile width too. */
.status-pill {
  display: inline-block;
  padding: .2rem .6rem;
  border-radius: 999px;
  font-size: .82rem;
  font-weight: 700;
  line-height: 1.3;
  white-space: nowrap;
}
.status-pill-success { background: #eaf7ef; color: #22683d; }
.status-pill-guidance { background: #edf4fb; color: #235f93; }
.status-pill-warning { background: #fff3d9; color: #775900; }
/* Fourth semantic colour, added for the urgency pill (overdue) — reuses
   the existing --red-bg/--red-text tokens already used for error message
   panels elsewhere, rather than introducing a new red. */
.status-pill-error { background: #fff0ea; color: #9b3b29; }
/* Category tag, not a status: same pill shape as the semantic states above,
   but deliberately grey/low-contrast so a task TYPE (e.g. "Camera review")
   never reads as a state the four real colours are reserved for. */
.status-pill-neutral { background: #eef0f2; color: #4a4f57; }

@media (max-width: 700px) {
  .status-pill { font-size: .78rem; padding: .18rem .5rem; }
}

/* Card-system brief — Tertiary tier: lower-emphasis actions, icon-left
   ghost treatment. Scoped to this one confirmed button via its own key,
   not a shared class/type — other "Back" buttons in the app were checked
   and are deliberately not swept into this, since that's a separate
   decision for each of them, not implied by this one. Padding is bumped
   past Figma's ~34-40px spec to a 44px minimum tap target: this is a
   field app, sometimes used with gloves, and STYLE_GUIDE.md's "field
   clarity first" principle takes priority over matching the visual spec's
   hit-area exactly. Placed in this final style block deliberately: earlier
   placement lost the background/color half of this rule to the later
   button[kind="secondary"] redeclarations elsewhere in this file, which
   tie on specificity and then win on cascade order. */
.st-key-back_followup_list button {
  background: rgba(0,0,0,.05) !important;
  border: none !important;
  border-radius: 999px !important;
  color: #F36C21 !important;
  font-weight: 700 !important;
  font-size: 14px !important;
  min-height: 44px !important;
  min-width: 44px !important;
  padding: 10px !important;
  box-shadow: none !important;
}
/* The visible label sits in a child span Streamlit renders inside the
   button, which the secondary-button rules elsewhere give its own explicit
   dark colour — override that descendant directly, not just the button. */
.st-key-back_followup_list button * {
  color: #F36C21 !important;
}
.st-key-back_followup_list button:hover {
  background: rgba(0,0,0,.09) !important;
}

/* Card-system brief — Tertiary tier, second confirmed use (trap-journey-
   scroll brief): the workflow "Exit to Trap sites" button. Same treatment
   as the necropsy back button above, scoped by its own key rather than a
   shared class, same reasoning — this button is load-bearing (the only way
   out of a workflow page while the top-nav "Trap sites" pill is routing-
   guarded there), so only the paint changes, not the click handler. */
.st-key-exit_workflow_to_sites button {
  background: rgba(0,0,0,.05) !important;
  border: none !important;
  border-radius: 999px !important;
  color: #F36C21 !important;
  font-weight: 700 !important;
  font-size: 14px !important;
  min-height: 44px !important;
  min-width: 44px !important;
  padding: 10px !important;
  box-shadow: none !important;
}
.st-key-exit_workflow_to_sites button * {
  color: #F36C21 !important;
}
.st-key-exit_workflow_to_sites button:hover {
  background: rgba(0,0,0,.09) !important;
}

/* Data quality tool — the same Tertiary/Primary mechanics as above, colour
   swapped to the semantic token that matches what each action means, not a
   new button type. Keys are per-candidate (check ID suffix), so these use a
   substring class match rather than one exact .st-key-<name> selector - one
   rule still covers every candidate's pair of buttons. Placed in this same
   final block for the identical cascade-order reason documented above. */
[class*="st-key-data_quality_confirm_"] button {
  background: rgba(0,0,0,.05) !important;
  border: none !important;
  border-radius: 999px !important;
  color: #22683D !important;
  font-weight: 600 !important;
  box-shadow: none !important;
}
[class*="st-key-data_quality_confirm_"] button * {
  color: #22683D !important;
}
[class*="st-key-data_quality_confirm_"] button:hover {
  background: rgba(0,0,0,.09) !important;
}
[class*="st-key-data_quality_void_"] button[kind="primary"] {
  background: #9B3B29 !important;
  border-color: #9B3B29 !important;
  color: #FFFFFF !important;
}
[class*="st-key-data_quality_void_"] button[kind="primary"] * {
  color: #FFFFFF !important;
}
[class*="st-key-data_quality_void_"] button[kind="primary"]:hover {
  background: #7d2f21 !important;
  border-color: #7d2f21 !important;
}

/* Trial performance brief Phase 2 — co-equal stat pair (Kill outcome card),
   the tooltip-gated grey-footer pattern (every stat card + the funnel), the
   amber actionable-pointer callout, and the restyled conversion funnel.
   Card content already sits inside a 15px-padded, 20px-radius container
   (the card system above) - .card-footer bleeds back out to that container's
   own edges via negative margin, rounding only its own bottom corners to
   match, rather than redefining the card shell itself. */
.coequal-row { display: flex; gap: 16px; }
.coequal-stat { flex: 1; }
.coequal-value { font-size: 26px; font-weight: 800; color: var(--text); line-height: 1.1; }
.coequal-value.success { color: var(--green-text); }
.coequal-label { font-size: 12px; color: var(--muted); margin-top: 2px; }

.action-callout {
  background: var(--amber-bg);
  color: var(--amber-text);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 12px;
  margin: 12px 0 0;
}

.card-footer {
  /* Darker than --card-bg (#f3f3f0) by the same proportion the mockup's
     footer (#f3f3f0) was darker than its own white card - #f3f3f0 alone
     is invisible against this app's actual (already grey) card body,
     confirmed live on staging: computed background was identical to the
     card behind it. */
  background: #E7E7E4;
  /* Bottom: 0, not a negative bleed like left/right - the card shell is a
     flex column (Streamlit's stVerticalBlock), where a negative bottom
     margin doesn't bleed the footer to the parent's edge the way negative
     left/right margins do; it pushes the footer's own box 15px past the
     card's rendered bottom entirely, outside the border, confirmed live
     via getBoundingClientRect (footer bottom 15px beyond card bottom).
     margin-bottom: 0 lands exactly flush with the card's true edge
     instead, verified the same way (0px diff). */
  margin: 12px -15px 0 -15px;
  padding: 12px 15px;
  border-radius: 0 0 20px 20px;
  font-size: 12px;
  color: var(--text);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  position: relative;
}
.info-icon {
  width: 15px; height: 15px;
  border-radius: 50%;
  border: 1.3px solid #B8BCC2;
  color: var(--muted);
  font-size: 10px; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}
.tooltip {
  position: absolute; bottom: 100%; left: 15px; margin-bottom: 6px;
  background: var(--text); color: #FFFFFF;
  font-size: 11px; font-weight: 400;
  padding: 8px 10px; border-radius: 8px; width: 220px; line-height: 1.4;
  opacity: 0; visibility: hidden; transition: opacity .15s; z-index: 10;
}
.tooltip.wide { width: 320px; }
.info-icon:hover + .tooltip,
.info-icon:focus + .tooltip,
.info-icon.tap-active + .tooltip { opacity: 1; visibility: visible; }

.funnel-row { display: grid; grid-template-columns: 140px 1fr 90px; align-items: center; gap: 14px; padding: 12px 0; border-bottom: 1px solid #F3F3F0; }
.funnel-row:last-child { border-bottom: none; }
.funnel-label { font-size: 13px; color: var(--text); font-weight: 500; }
.funnel-count { font-size: 11px; color: var(--muted); margin-top: 2px; }
.funnel-bar-track { height: 8px; background: #F3F3F0; border-radius: 999px; overflow: hidden; }
.funnel-bar-fill { height: 100%; background: var(--brand-orange); border-radius: 999px; }
.funnel-conversion { font-size: 20px; font-weight: 800; color: var(--brand-orange); text-align: right; }
.funnel-conversion .sub { display: block; font-size: 10px; font-weight: 500; color: var(--muted); }
.funnel-conversion.base { font-size: 14px; font-weight: 500; color: var(--muted); }
.main-loss { background: var(--amber-bg); color: var(--amber-text); border-radius: 10px; padding: 12px 14px; font-size: 13px; margin: 4px 0 0; }

/* Trial performance brief 2c — mockup value (19px/600); flagged in the brief
   itself as needing judgment in real rendered context against the page's
   34px-ish H1 and 22px card titles, not a value to treat as final on sight. */
.page-context-emphasis { font-size: 19px !important; font-weight: 600 !important; color: var(--text) !important; }

@media (max-width: 700px) {
  .funnel-row { grid-template-columns: 100px 1fr 70px; gap: 10px; }
  .funnel-conversion { font-size: 17px; }
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

connection_status_watcher()

require_authentication()

data = load_data()
apply_timezone_correction_migration(data)
apply_mouse_weight_reclassification_migration(data)
if not st.session_state.get("photo_cleanup_done"):
    _completed_necropsy_ids = data["Followups"][
        (data["Followups"]["Follow-up Type"] == "Necropsy review") & (data["Followups"]["Status"] == "Complete")
    ]["Follow-up ID"].astype(str).tolist()
    cleanup_stale_transactions(
        DATA_ROOT,
        data["Checks"]["Check ID"].astype(str).tolist() + _completed_necropsy_ids,
    )
    st.session_state.photo_cleanup_done = True

WORKFLOW_PAGES = {"site", "start_visit", "visit", "check", "check_confirm"}

if "page" not in st.session_state:
    _resume_site_id = st.query_params.get(WORKFLOW_QUERY_KEY_SITE, "")
    _resume_visit_id = st.query_params.get(WORKFLOW_QUERY_KEY_VISIT, "")
    _resume_trap_id = st.query_params.get(WORKFLOW_QUERY_KEY_TRAP, "")
    _resume_visit_row = validate_workflow_resume(data, _resume_site_id, _resume_visit_id, _resume_trap_id)
    if _resume_visit_row is None:
        # No candidate, or a stale/invalid one: discard silently and land
        # exactly where a normal fresh visit always has.
        clear_workflow_query_params()
        st.session_state.page = "sites"
    else:
        # Validated, but never auto-resume: a stale bookmark reopened hours
        # later can validate as "technically still open" (single
        # active-editor constraint), so ask before jumping back in.
        st.title("Resume checking?")
        message_panel(
            "guidance",
            f"Resume checking {_resume_trap_id} at {site_name(data, _resume_site_id)}?",
            ["A dropped connection left this check in progress."],
        )
        resume_col, start_over_col = st.columns(2)
        if resume_col.button("Resume", type="primary", use_container_width=True, key="workflow_resume_confirm"):
            navigate("check", site_id=_resume_site_id, visit_id=_resume_visit_id, trap_id=_resume_trap_id)
        if start_over_col.button("Start over", use_container_width=True, key="workflow_resume_start_over"):
            clear_workflow_query_params()
            navigate("sites")
        st.stop()
if "field_operator" not in st.session_state: st.session_state.field_operator = "Jake"


def select_top_navigation(target: str, allowed_pages: set[str]) -> None:
    """Sync framework top navigation with the app's existing workflow router."""
    current = st.session_state.get("page", "sites")
    if current not in allowed_pages:
        if current in WORKFLOW_PAGES and target not in WORKFLOW_PAGES:
            clear_workflow_query_params()
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


def top_nav_data_quality() -> None:
    select_top_navigation("data_quality", {"data_quality"})


def top_nav_sign_out() -> None:
    clear_workflow_query_params()
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
PAGE_DATA_QUALITY = st.Page(
    top_nav_data_quality, title="Data quality", url_path="data-quality"
)
PAGE_SIGN_OUT = st.Page(top_nav_sign_out, title="Sign out", url_path="sign-out")

NAVIGATION_PAGES = {
    "": [PAGE_TRAP_SITES, PAGE_FOLLOWUPS, PAGE_PERFORMANCE],
    "Administration": [PAGE_TRAPS, PAGE_TRIAL_SETUP, PAGE_DATA_RECORDS, PAGE_DATA_QUALITY, PAGE_SIGN_OUT],
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
    # Streamlit doesn't unmount/remount this popover across a rerun triggered
    # from inside it (its own open/closed state is local, uncontrolled React
    # state, not tied to session_state) - so a page_link click that navigates
    # away leaves it sitting open over the new page's content. Keying it to
    # the current page forces a fresh component identity (and therefore a
    # fresh, closed popover) on every real navigation, without needing to
    # track open/closed state ourselves.
    with st.popover("Administration", key=f"app_top_navigation_admin_popover_{st.session_state.get('page', 'sites')}"):
        # UX-audit fix (2026-08-13): this was the only place in the live app that
        # could set the operator name attributed to a visit/check - the sole
        # <text_input> for it lived in a dead, unreachable page handler, so every
        # visit was silently attributed to whatever the hardcoded default happened
        # to be. Reachable from every page via the top nav, same as Sign out below.
        st.session_state.field_operator = st.text_input(
            "Operator",
            value=st.session_state.field_operator,
            key="top_nav_operator",
            help="Attributed to every visit and check you record until changed.",
        )
        st.divider()
        st.page_link(PAGE_TRAPS, label="Traps", width="stretch")
        st.page_link(PAGE_TRIAL_SETUP, label="Trial setup", width="stretch")
        st.page_link(PAGE_DATA_RECORDS, label="Data & records", width="stretch")
        data_quality_candidate_count = len(find_data_quality_candidates(data))
        if data_quality_candidate_count:
            # The badge's count is baked directly into the CSS content string
            # rather than styled unconditionally, so the highlighted
            # background and count pill only ever render when there really
            # are candidates waiting - nothing to hide/show client-side.
            st.markdown(
                f"""<style>
                [data-testid="stPageLink"]:has(a[href*="data-quality"]) {{
                    background: #FFF3D9 !important;
                    border-radius: 8px;
                }}
                [data-testid="stPageLink"]:has(a[href*="data-quality"]) a::after {{
                    content: "{data_quality_candidate_count}";
                    background: #775900;
                    color: #FFFFFF;
                    font-size: 10px;
                    font-weight: 700;
                    border-radius: 999px;
                    padding: 1px 6px;
                    margin-left: 6px;
                }}
                </style>""",
                unsafe_allow_html=True,
            )
        st.page_link(PAGE_DATA_QUALITY, label="Data quality", width="stretch")
        st.divider()
        if st.button("Sign out", key="top_nav_sign_out", use_container_width=True):
            clear_workflow_query_params()
            # The signed access token in the URL is what lets a refresh survive
            # without re-prompting (see require_authentication) - it must be
            # cleared here too, or a rerun immediately re-authenticates from the
            # still-valid URL and Sign out has no effect.
            st.query_params.pop(AUTH_QUERY_KEY, None)
            st.session_state.clear()
            st.rerun()

# Workflow pages retain one explicit escape route while the top navigation
# remains on the parent Trap sites section. No separate site-name caption
# here any more (trap-journey-scroll brief) — every workflow page's own H1
# already carries that context, so a line above this button was showing the
# same name twice.
if st.session_state.page in WORKFLOW_PAGES:
    if st.button("← Exit to Trap sites", key="exit_workflow_to_sites"):
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
            status_kind = "warning" if active_complete else "guidance"
        else:
            # Card-system brief Phase 2: an absolute Last/Next date line no
            # longer appears on this card (moved to the visit page) — this
            # is its replacement, and it's the only pill a not-yet-started
            # site shows. A freshly-completed site (completed_today) is
            # simply not due soon, so it now shows no pill here, same as
            # any other site with time before its next check — the pale
            # green card background below is still its own, separate signal.
            status_text, status_kind = site_urgency_pill(next_dt.date(), now().date())
        with app_card():
            if completed_today and active is None:
                st.markdown('<span class="site-complete-marker" aria-hidden="true"></span>', unsafe_allow_html=True)
            # Trap count is shown once: as a fraction while a visit is in
            # progress (matches the "X of Y" language already used
            # elsewhere), or as a plain count before one starts — never both,
            # since showing "9 active traps" next to "0 of 9 traps checked"
            # repeats the same number for no reason.
            trap_count_text = (
                f"{len(checks)} of {len(traps)} traps checked" if active is not None
                else f"{len(traps)} active traps"
            )
            st.markdown(
                '<div class="shared-card-copy site-card-compact">'
                f'<div class="shared-card-heading"><strong>{html.escape(str(s["Site Name"]))}</strong>{status_pill(status_text, status_kind)}</div>'
                f'<div class="shared-card-meta">{trap_count_text} · Every {interval} days</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            if active is not None:
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

    # Trap-journey-scroll brief: someone standing at one physical trap is not
    # usually filtering or searching, so both fields live behind one toggle,
    # default closed. Read prior widget state directly from session_state
    # rather than only from the (possibly unrendered) widgets themselves —
    # Streamlit keeps a widget's value in session_state after it stops being
    # drawn, so an active filter still applies to the list even while its
    # controls are hidden, and the toggle label surfaces what's active so it
    # isn't silently discarded from view.
    product_filter_key = f"visit_product_filter_{vid}"
    search_key = f"visit_trap_search_{vid}"
    prior_product_filter = st.session_state.get(product_filter_key, "All")
    prior_search_text = st.session_state.get(search_key, "").strip()
    filter_active = prior_product_filter != "All" or bool(prior_search_text)

    toggle_label = "Filter or search traps"
    if filter_active:
        active_bits = []
        if prior_product_filter != "All":
            active_bits.append(prior_product_filter)
        if prior_search_text:
            active_bits.append(f'"{prior_search_text}"')
        toggle_label += " · " + " · ".join(active_bits)

    # Keyed by vid, not persisted anywhere else, so a new visit always starts
    # closed — no remembered state across visits or page loads.
    filter_expanded = st.toggle(toggle_label, key=f"visit_filter_expanded_{vid}", value=False)
    if filter_expanded:
        filter_col, search_col = st.columns([1, 1.6])
        product_filter = filter_col.radio(
            "Trap type",
            ["All", "R1", "M1"],
            horizontal=True,
            key=product_filter_key,
        )
        search_text = search_col.text_input(
            "Find trap",
            placeholder="Trap ID or location",
            key=search_key,
        ).strip().lower()
    else:
        product_filter = prior_product_filter
        search_text = prior_search_text.lower()

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

    # Trap-journey-scroll brief: this is the card-system brief's Phase 2
    # schedule line, relocated to the bottom of the trap list rather than
    # between the H1 and the cards where it previously sat — read-only
    # reference for someone already inside a visit, not something that
    # needs to compete with the cards for the first-viewport scroll budget.
    site_row_for_schedule = data["Sites"][data["Sites"]["Site ID"] == sid]
    if not site_row_for_schedule.empty:
        schedule_interval = int(float(site_row_for_schedule.iloc[0]["Visit Interval Days"] or 3))
        schedule_last = latest_completed_visit(data, sid)
        schedule_last_dt = parse_dt(schedule_last["End Time"]) if schedule_last is not None else None
        schedule_next_dt = schedule_last_dt + timedelta(days=schedule_interval) if schedule_last_dt else now()
        st.caption(
            f"Last {schedule_last_dt.strftime('%d %b %Y') if schedule_last_dt else 'not completed'} · "
            f"Next {'due now' if schedule_next_dt.date() <= now().date() else schedule_next_dt.strftime('%d %b %Y')}"
        )

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
        if checked_count == 0:
            # Only offered while nothing has been recorded under this visit
            # yet — the moment a single trap is checked, there's real field
            # data attached to it and this option disappears entirely, so
            # it can never be used to discard actual work. No separate
            # confirm step: at 0 checks there's nothing to lose, and the
            # worst case of a stray tap is just re-tapping "Start checking".
            if st.button("Cancel check", key=f"cancel_visit_{vid}", use_container_width=True):
                audit_change(data, "Visit", vid, "Status", "In progress", "Cancelled (no traps checked)", "Cancelled from Site check actions")
                data["Visits"] = data["Visits"][data["Visits"]["Visit ID"] != vid]
                save_data(data)
                set_flash("success", f"{site_name(data, sid)} check cancelled", ["No traps had been recorded, so nothing was lost."])
                go("sites")

elif page == "check":
    sid, vid, trap_id = st.session_state.site_id, st.session_state.visit_id, st.session_state.trap_id
    tr = trap_row(data, trap_id)
    w = open_window(data, trap_id)

    # Extracted to a closure so progressive disclosure and save-validation
    # can use plain `return` instead of st.stop() (Layout stability pass,
    # R1_M1_Agreed_Release_Sequence_Updated.md). st.stop() halts the ENTIRE
    # script for this rerun, not just this page - anything after the whole
    # page-routing if/elif chain (e.g. scroll_to_top_once() at the very
    # bottom of the file) silently never ran whenever this page stopped
    # early. `return` only exits this page's own render function, which is
    # both what was actually intended and a real, if minor, existing bug
    # fix on its own.
    def _render_check_page():
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
            return

        st.caption(f"Current window · {w['Build Version']} · started {human_dt(w['Start Time'])}")
        finding = st.radio(
            "What did you find?",
            FINDINGS,
            index=None,
            key=f"finding_{trap_id}_{vid}",
        )
        if finding is None:
            st.caption("Choose one finding to continue.")
            return

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

        # True one-tap saving lock (Layout stability pass): the "Saving
        # check… Do not tap again." message used to be text only, with
        # nothing actually disabling the button behind it - the only real
        # disabled= condition was photo_blocked. On a slow field connection
        # a second tap during a slow save could still resubmit. This flag
        # is set the instant the button is pressed and persists across the
        # rerun it triggers, so the button itself renders disabled on any
        # subsequent rerun until the save fails validation (cleared, so the
        # operator can fix and retry) or completes (popped, along with the
        # rest of this check's transient session_state).
        save_lock_key = f"check_saving_{trap_id}_{vid}"
        saving = st.session_state.get(save_lock_key, False)
        save_label = "Please wait" if photo_blocked else ("Saving…" if saving else "Save check")
        if st.button(save_label, type="primary", key=f"save_check_{trap_id}_{vid}", use_container_width=True, disabled=photo_blocked or saving):
            st.session_state[save_lock_key] = True
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
                st.session_state[save_lock_key] = False
                message_panel("error", "Complete these details before saving.", errors)
                return

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
                    st.session_state[save_lock_key] = False
                    st.error("One or more selected photos are not safely stored yet.")
                    return
            active = open_window(data, trap_id)
            if active is None:
                st.session_state[save_lock_key] = False
                message_panel("error", "This trap has no active test window.", ["Start it from deployment time and retry."])
                if st.button("Start missing window", key=f"repair_on_save_{trap_id}_{vid}"):
                    repair_missing_window(data, trap_id)
                    st.rerun()
                return

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
                "", "",
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

            def _verify_check_persisted(reloaded):
                persisted_check = reloaded["Checks"][reloaded["Checks"]["Check ID"].astype(str) == str(check_id)]
                persisted_followups = reloaded["Followups"][reloaded["Followups"]["Visit ID"].astype(str) == str(vid)]
                if len(persisted_check) != 1:
                    raise RuntimeError("The saved workbook did not contain exactly one completed check.")
                return {"followup_count": len(persisted_followups)}

            photo_count = commit_staged_records_with_photos(
                data=data,
                staged=staged,
                original_data=original_data,
                photo_gate=photo_gate,
                expected_photo_count=expected_photo_count,
                record_id=check_id,
                photos_id_column="Check ID",
                verify_persisted=_verify_check_persisted,
                log_prefix="check",
                log_fields={"check_id": check_id, "trap_id": trap_id},
                record_noun="check",
                record_description="check, follow-up or photo record",
                session_state_keys_to_clear_on_failure=[save_lock_key],
            )

            for key in [
                f"bag_id_{vid}_{trap_id}",
                pending_check_id_key(vid, trap_id),
                photo_component_event_key(vid, trap_id),
                save_lock_key,
            ]:
                st.session_state.pop(key, None)
            st.session_state.saved_check = {
                "trap_id": trap_id,
                "photo_count": photo_count,
            }
            go("visit", site_id=sid, visit_id=vid)

    _render_check_page()

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
                build_prefix = f"{tr['Product']} Build "
                build_raw = str(tr["Build Version"] or "—")
                build_text = build_raw[len(build_prefix):] if build_raw.startswith(build_prefix) else build_raw
                render_compact_card_content(
                    title=trap_id,
                    right_label=site_name(data, tr["Site ID"]),
                    main_line=trap_location_label(tr),
                    meta_line=(
                        f"Build: {build_text} · "
                        f"{len(kills)} kill{'s' if len(kills) != 1 else ''} · "
                        f"{len(trap_checks)} check{'s' if len(trap_checks) != 1 else ''}"
                    ),
                    meta_line_2=f"Last kill: {last_kill}",
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
                    bag_text = f"Bag: {item_row['Bag ID']} · " if str(item_row.get("Bag ID", "")).strip() else ""
                    reason_text = item_row["Reason"] or "—"
                    # Priority is shown plainly, same as before — an explicit decision,
                    # not the unresolved default: this card doesn't give High any
                    # extra visual weight (no colour, no icon), since that's a separate
                    # design decision this release isn't making. If that changes later,
                    # it should be a deliberate follow-up, not a silent addition here.
                    st.markdown(
                        '<div class="shared-card-copy">'
                        f'<div class="shared-card-heading"><strong>{html.escape(str(item_row["Trap ID"]))}</strong>{status_pill(str(item_row["Follow-up Type"]), "neutral")}</div>'
                        f'<div class="shared-card-meta">{html.escape(site_name(data,item_row["Site ID"]))} · {html.escape(str(item_row["Priority"]))}</div>'
                        f'<div class="shared-card-meta">{html.escape(bag_text)}Reason: {html.escape(str(reason_text))}</div>'
                        f'<div class="shared-card-meta">Created: {html.escape(human_dt(item_row["Created Time"]))}</div>'
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

            context_rows=[("Trap",item["Trap ID"]),("Site",site_name(data,item["Site ID"])),("Build",tr["Build Version"]),("Camera",str(tr["Camera ID"]).strip() or "No camera assigned"),("Bag ID",item["Bag ID"]),("Reason",item["Reason"] or "Not recorded")]
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
                st.markdown("### Photos")
                st.caption("Attach photos of the animal for the trial record. Same upload behaviour as trap-check photos — select multiple, each uploads independently.")
                photo_gate=render_followup_photo_capture(item)
                status=st.selectbox("Necropsy status",["Select…","Complete","Not completed","Unable to assess"],index=0,key=f"{prefix}_status")
                assessment=st.selectbox("Necropsy assessment",["Select…","Supports humane kill","Does not support humane kill","Unclear","Not assessable"],index=0,key=f"{prefix}_assessment")
                weight_range=st.selectbox("Animal weight range",["Select…"]+weight_ranges_for_species(linked_window["Species"] if linked_window is not None else None),index=0,key=f"{prefix}_weight")
                final=st.selectbox("Final humane-kill result",["Select…","Yes","No","Unclear","Not assessable"],index=0,key=f"{prefix}_final")
                saving_update("The linked kill result, humane-kill KPI, test-window review status and the attached photos.")
                photo_blocked=bool(photo_gate.get("expected_count",0) and not photo_gate.get("ready"))
                if photo_gate.get("expected_count",0):
                    if photo_gate.get("manual_failure_count",0):
                        count=int(photo_gate["manual_failure_count"])
                        st.caption(f"{count} photo{'s' if count != 1 else ''} could not upload")
                    elif photo_gate.get("ready"):
                        st.caption(f"{photo_gate['file_count']} photo{'s' if photo_gate['file_count'] != 1 else ''} saved")
                    else:
                        remaining=max(1,photo_gate.get("expected_count",0)-photo_gate.get("file_count",0))
                        st.caption(f"Uploading {remaining} photo{'s' if remaining != 1 else ''}…")
                save_label="Please wait" if photo_blocked else "Save necropsy review"
                submit=st.button(save_label,type="primary",key=f"{prefix}_save",disabled=photo_blocked)
                if submit:
                    errors=[]
                    if "Select…" in [status,assessment,weight_range,final]: errors.append("Complete all required necropsy fields.")
                    errors.extend(necropsy_consistency_errors(status,assessment,final))
                    idxs=data["Windows"].index[data["Windows"]["Window ID"]==item["Window ID"]].tolist()
                    if not idxs: errors.append("The linked test window cannot be found.")
                    if errors:
                        st.error("Please correct the necropsy review:\n\n" + "\n".join(f"- {err}" for err in errors))
                    else:
                        expected_photo_count=int(photo_gate.get("expected_count",0))
                        if expected_photo_count:
                            # Verify again at the final commit boundary using the durable pending manifest.
                            photo_gate={
                                **photo_gate,
                                **verify_pending_photo_transaction(DATA_ROOT,photo_gate["context"],MAX_SAVED_PHOTO_BYTES),
                            }
                            if not (
                                photo_gate.get("ready")
                                and photo_gate.get("expected_count")==photo_gate.get("file_count")==photo_gate.get("row_count")
                            ):
                                st.error("One or more selected photos are not safely stored yet.")
                                st.stop()

                        original_data={name: frame.copy(deep=True) for name, frame in data.items()}
                        staged={name: frame.copy(deep=True) for name, frame in data.items()}
                        idx=idxs[0]
                        for k,v in {"Necropsy Status":status,"Necropsy Assessment":assessment,"Animal Weight Range":weight_range,"Final Humane Kill":final}.items(): staged["Windows"].at[idx,k]=v
                        fidx=staged["Followups"].index[staged["Followups"]["Follow-up ID"]==fid][0]
                        staged["Followups"].at[fidx,"Status"]="Complete"; staged["Followups"].at[fidx,"Completed Time"]=dtstr()
                        refresh_review_status(staged,item["Window ID"])

                        def _verify_necropsy_persisted(reloaded):
                            persisted_followup=reloaded["Followups"][reloaded["Followups"]["Follow-up ID"].astype(str)==str(fid)]
                            if len(persisted_followup)!=1 or str(persisted_followup.iloc[0]["Status"])!="Complete":
                                raise RuntimeError("The saved workbook did not show this necropsy review as complete.")
                            return {}

                        commit_staged_records_with_photos(
                            data=data,
                            staged=staged,
                            original_data=original_data,
                            photo_gate=photo_gate,
                            expected_photo_count=expected_photo_count,
                            record_id=fid,
                            photos_id_column="Follow-up ID",
                            verify_persisted=_verify_necropsy_persisted,
                            log_prefix="necropsy",
                            log_fields={"follow_up_id": fid, "trap_id": item["Trap ID"]},
                            record_noun="necropsy review",
                            record_description="necropsy review or photo record",
                        )

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
                    c1.markdown(f"**{row_wid}**" + (" " + status_pill("Excluded", "warning") if wr_row.get("Excluded") == "Yes" else ""), unsafe_allow_html=True)
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
                if wr.get("Excluded") == "Yes":
                    message_panel("warning", "Excluded from Trial performance", [wr.get("Exclusion Reason") or "No reason recorded."])
                for label,col in [("Status","Status"),("Started","Start Time"),("Closed","End Time"),("Physical finding","Finding At Close"),("Outcome","Outcome"),("Target present","Target Present"),("Video assessment","Video Assessment"),("Necropsy assessment","Necropsy Assessment"),("Animal weight range","Animal Weight Range"),("Final humane kill","Final Humane Kill"),("Review status","Review Status")]:
                    value = human_dt(wr[col]) if col in ["Start Time", "End Time"] else (wr[col] or "—")
                    if col == "Status" and value == "Open": value = "Active"
                    st.write(f"**{label}:** {value}")
                if wr["Status"] == "Open":
                    helper("This window is still active. Evidence and final assessment are added only after the next field check closes it.")
                if st.button("Close panel", key="close_window_panel"): st.session_state.pop("window_panel",None); st.rerun()

elif page == "data_quality":
    header("Data quality review", "Checks with no other trap activity nearby at the same site, worth a human look before they're treated as real field data.")
    candidates = find_data_quality_candidates(data)
    reviewing_id = st.session_state.get("data_quality_review")

    if not candidates:
        st.session_state.pop("data_quality_review", None)
        st.success("No flagged checks right now — every check either has real activity nearby at its site, or has already been reviewed.")
    elif reviewing_id and reviewing_id not in {c["Check ID"] for c in candidates}:
        # Resolved (confirmed or voided) since this panel opened, or no longer a candidate for any other reason.
        st.session_state.pop("data_quality_review", None)
        st.rerun()
    elif reviewing_id:
        candidate = next(c for c in candidates if c["Check ID"] == reviewing_id)
        position = next(i for i, c in enumerate(candidates) if c["Check ID"] == reviewing_id) + 1
        if st.button("← Back to list", key="data_quality_back"):
            st.session_state.pop("data_quality_review", None)
            st.rerun()
        st.caption(f"Reviewing candidate {position} of {len(candidates)}")
        st.subheader(candidate["Trap ID"])
        st.caption(site_name(data, candidate["Site ID"]))

        workflow_context([
            ("Check time", human_dt(candidate["Check Time"], include_year=True)),
            ("Finding", candidate["Finding"]),
            ("Window closed → new window", human_dt(candidate["Check Time"], include_year=True)),
        ])

        before_txt = f"the closest earlier check at this site was {human_dt(candidate['closest_before'], include_year=True)}" if candidate["closest_before"] is not None else "no earlier check at this site was found"
        after_txt = f"the closest later check was {human_dt(candidate['closest_after'], include_year=True)}" if candidate["closest_after"] is not None else "no later check at this site was found yet"
        message_panel(
            "warning",
            f"No other activity at {site_name(data, candidate['Site ID'])} nearby",
            [f"{before_txt[0].upper()}{before_txt[1:]}, and {after_txt} — nothing else was checked within {DATA_QUALITY_ISOLATION_WINDOW_MINUTES} minutes of this record."],
        )

        st.markdown("**Reason (required if voiding)**")
        void_reason = st.text_area(
            "Reason for voiding",
            key=f"data_quality_reason_{reviewing_id}",
            placeholder="e.g. Confirmed this was a UI test click during setup, not a real field visit.",
            label_visibility="collapsed",
        )
        confirm_col, void_col = st.columns(2)
        with confirm_col:
            if st.button("Confirm as real", key=f"data_quality_confirm_{reviewing_id}", use_container_width=True):
                confirm_check_as_real(data, reviewing_id)
                st.session_state.pop("data_quality_review", None)
                set_flash("success", "Confirmed as real.", ["No data was changed.", "This check will not be flagged again."])
                st.rerun()
        with void_col:
            if st.button("Void as test data", key=f"data_quality_void_{reviewing_id}", type="primary", use_container_width=True):
                if not void_reason.strip():
                    st.error("Enter a reason before voiding this record.")
                else:
                    try:
                        void_check_as_test_data(data, reviewing_id, void_reason)
                        st.session_state.pop("data_quality_review", None)
                        set_flash("success", "Voided as test data.", ["Excluded from Trial performance and the camera funnel.", "The original record remains in the workbook, marked excluded.", "Recorded in the audit log."])
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
    else:
        st.caption(f"{len(candidates)} check{'s' if len(candidates) != 1 else ''} flagged for review — each was checked with no other trap activity nearby at the same site.")
        for c in candidates:
            with app_card():
                cols = st.columns([3, 1])
                cols[0].markdown(f"**{c['Trap ID']} · {site_name(data, c['Site ID'])}**")
                cols[1].caption(human_dt(c["Check Time"], include_year=True))
                st.caption(f"No other traps at this site checked within {DATA_QUALITY_ISOLATION_WINDOW_MINUTES} minutes")
                if st.button("Review", key=f"data_quality_open_{c['Check ID']}"):
                    st.session_state.data_quality_review = c["Check ID"]
                    st.rerun()

elif page == "results":
    install_grey_footer_tooltips()
    header("Trial performance",
        "Do we have enough evidence to launch? Efficacy against the humane-kill and time-to-kill targets, trial-wide.",
        emphasize_subtitle=True,
    )
    with app_card():
        product_col,build_col,site_col,export_col=st.columns([1,1.65,1,0.8],vertical_alignment="bottom")
        product=product_col.selectbox("Trap type",sorted(data["Builds"]["Product"].unique()))
        builds=data["Builds"][data["Builds"]["Product"]==product]
        current=builds[builds["Build Status"]=="Current"]["Build Version"].tolist()
        selected=build_col.selectbox("Build to assess",["Latest active build"]+builds["Build Version"].tolist()+["Compare builds","All builds — use with care"])
        site=site_col.selectbox("Site",["All sites"]+data["Sites"]["Site ID"].tolist(),format_func=lambda x:x if x=="All sites" else site_name(data,x))

    windows=data["Windows"][(data["Windows"]["Product"]==product)&(data["Windows"]["Status"]=="Closed")&(data["Windows"]["Excluded"]!="Yes")].copy()
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
    within_target=timed_kills[timed_kills["Interaction To Kill Numeric"] < TIME_TO_KILL_TARGET_MINUTES]
    missed_target=timed_kills[timed_kills["Interaction To Kill Numeric"] >= TIME_TO_KILL_TARGET_MINUTES]
    timing_pending=physical_kills[~physical_kills["Window ID"].isin(timed_kills["Window ID"])]
    target_rate=len(within_target)/len(timed_kills)*100 if len(timed_kills) else None
    interaction_to_kill=timed_kills["Interaction To Kill Numeric"].median() if len(timed_kills) else None

    kill_evidence_complete=physical_kills[physical_kills["Final Humane Kill"].isin(["Yes","No"])]
    camera_windows=windows[windows["Camera Assigned"]=="Yes"].copy()
    camera_reviews_complete=camera_windows[camera_windows["Review Status"]=="Complete"]
    camera_reviews_open=camera_windows[camera_windows["Review Status"]=="Open"]
    unusable=camera_windows[camera_windows["Evidence Usable"]=="No"]

    outcome_card,time_card,evidence_card=st.columns(3)
    with outcome_card:
        with app_card():
            st.markdown("#### Kill outcome")
            coequal_stats([
                (len(humane), "good kills", ""),
                (f"{humane_rate:.0f}%" if humane_rate is not None else "—", "humane", "success" if humane_rate is not None else ""),
            ])
            if len(final_pending):
                action_callout(f"→ {len(final_pending)} kill{'s' if len(final_pending)!=1 else ''} awaiting final assessment — see Results needing attention")
            card_footer(
                "Necropsy-dependent",
                f"Necropsy = physical examination of the collected animal. Based on {assessed_kills} of {len(physical_kills)} confirmed kills with a completed necropsy assessment.",
            )
    with time_card:
        with app_card():
            st.markdown("#### Time to kill")
            st.metric("Met <24 hr target",f"{len(within_target)} of {len(timed_kills)}" if len(timed_kills) else "—")
            st.write(f"**Median: {human_duration(minutes=interaction_to_kill)}**" if interaction_to_kill is not None else "**No usable timing yet**")
            # Coverage relative to the full physical-kill population, not just the
            # internal met/missed split within the timed sample - "8 of 10 met
            # target" reads very differently depending on whether that "10" is
            # 90% or 15% of all confirmed kills.
            if len(physical_kills):
                if len(timed_kills) == len(physical_kills):
                    st.caption(f"All {len(physical_kills)} confirmed kill{'s' if len(physical_kills)!=1 else ''} have usable timing")
                else:
                    st.caption(f"{len(timed_kills)} of {len(physical_kills)} total kill{'s' if len(physical_kills)!=1 else ''} have usable timing")
            card_footer(
                "Camera-dependent",
                f"Camera review = watching footage of the event. Based on {len(timed_kills)} of {len(physical_kills)} confirmed kills with usable, camera-reviewed footage timing.",
            )
    with evidence_card:
        with app_card():
            st.markdown("#### Evidence")
            st.metric("Kill assessments complete",f"{len(kill_evidence_complete)} of {len(physical_kills)}")
            st.caption(f"Camera reviews complete: {len(camera_reviews_complete)} of {len(camera_windows)}")
            if not len(windows): st.caption("No closed windows in this selection")
            card_footer(
                "Coverage card",
                f"Open camera reviews: {len(camera_reviews_open)} · Unusable footage: {len(unusable)} — explains the denominators on the other two cards.",
            )

    # Only surface exceptions that could change the decision.
    attention=confirmed_kills[
        (confirmed_kills["Final Humane Kill"]=="No") |
        (confirmed_kills["Interaction To Kill Numeric"] >= TIME_TO_KILL_TARGET_MINUTES) |
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
    # Stage count, order, labels, conversion calculation and "main loss"
    # selection logic below are unchanged from before this restyle - Trial
    # performance brief 2h locks this section's visuals once shipped, and
    # the brief is explicit that the underlying logic must stay
    # byte-identical, not just look the same.
    stages=[("Rat interacted",len(interacted)),("Meaningful entry",len(entered)),("Trap activated",len(activated)),("Rat killed",len(killed)),("Humane kill",len(humane_funnel))]
    base=max(1,len(interacted))
    with app_card():
        rows_html=[]
        for i,(label,count) in enumerate(stages):
            prior=stages[i-1][1] if i else None
            conversion=(count/prior*100) if prior else None
            bar_pct=min(100,count/base*100)
            if conversion is None:
                conversion_html='<div class="funnel-conversion base">base</div>'
            else:
                conversion_html=f'<div class="funnel-conversion">{conversion:.0f}%<span class="sub">from prior</span></div>'
            rows_html.append(
                '<div class="funnel-row">'
                f'<div><div class="funnel-label">{html.escape(label)}</div><div class="funnel-count">{count} window{"s" if count!=1 else ""}</div></div>'
                f'<div class="funnel-bar-track"><div class="funnel-bar-fill" style="width:{bar_pct:.0f}%"></div></div>'
                f'{conversion_html}'
                '</div>'
            )
        st.markdown("".join(rows_html), unsafe_allow_html=True)
        if len(interacted):
            losses=[("did not make meaningful entry",len(interacted)-len(entered)),("entered but did not activate",len(entered)-len(activated)),("activated but were not killed",len(activated)-len(killed)),("were killed but not confirmed humane",len(killed)-len(humane_funnel))]
            loss_label,loss_count=max(losses,key=lambda x:x[1])
            if loss_count>0:
                st.markdown(f'<div class="main-loss">Main loss: {loss_count} reviewed camera window{"s" if loss_count!=1 else ""} with rat interaction {loss_label}.</div>', unsafe_allow_html=True)
        else:
            helper("No reviewed camera windows with target interaction are available for this selection.")
        card_footer(
            "Camera-sampled evidence",
            f"{len(camera_traps)} of {len(total_product_traps)} active traps have cameras · {len(reviewed_camera)} of {len(camera_windows)} closed camera windows reviewed with usable footage. This funnel reflects that sample, not every kill trial-wide."
            '<br><br><b>Terms:</b> a "window" is one monitoring period for a trap, between two checks — opens when a trap is set or reset, closes whenever the next check happens, whatever the outcome. Stages: Rat interacted (detected at/near the trap) → Meaningful entry (entered far enough to potentially trigger it) → Trap activated (mechanism fired) → Rat killed → Humane kill (met the humane standard). Each stage is a subset of the one before it.',
            wide=True,
        )

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
            met=len(gp_timed[gp_timed["Interaction To Kill Numeric"] < TIME_TO_KILL_TARGET_MINUTES])
            missed=len(gp_timed[gp_timed["Interaction To Kill Numeric"] >= TIME_TO_KILL_TARGET_MINUTES])
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
            # Rat and mouse bands are two different scales sharing one column
            # (a mouse's "0–10 g" isn't the same band as a rat's "0–50 g"),
            # so they can't be merged into one ascending-by-gram order without
            # inventing a meaningless cross-species ranking. Keep them as two
            # internally-ordered groups instead - rat bands first (unchanged
            # from before mice had their own scale), then mouse bands, then
            # Unknown last - rather than letting every mouse band collapse
            # into the same "not found" bucket as genuinely unknown weights.
            all_bands=RAT_WEIGHT_RANGES+MOUSE_WEIGHT_RANGES
            order={band:i for i,band in enumerate(all_bands)}; order["Unknown"]=len(all_bands)
            breakdown_df["_order"]=breakdown_df[breakdown].map(order).fillna(len(all_bands))
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
        st.markdown(status_pill(existing["Status"], "success" if existing["Status"] == "Active" else "none"), unsafe_allow_html=True)
        st.caption("Use Activate trap / Deactivate trap below to change status - it opens or closes a monitoring window, so it isn't a plain field edit.")
        notes = st.text_area("Notes", value=existing["Notes"])
        save_edit = st.form_submit_button("Save changes", type="primary")
    if save_edit:
        idx = data["Traps"].index[data["Traps"]["Trap ID"] == trap_id][0]
        data["Traps"].at[idx, "Location"] = location.strip()
        data["Traps"].at[idx, "Camera ID"] = camera.strip()
        data["Traps"].at[idx, "Route Order"] = str(order)
        data["Traps"].at[idx, "Notes"] = notes
        save_data(data)
        set_flash("success", f"{trap_id} updated.")
        go("setup")

    st.divider()
    if existing["Status"] == "Active":
        with st.expander("Deactivate trap"):
            deactivate_reason = st.text_area("Reason for deactivation", key=f"deactivate_reason_{trap_id}")
            deactivate_date = st.date_input("Effective date", value=now().date(), key=f"deactivate_date_{trap_id}")
            deactivate_time = st.time_input("Effective time", value=now().time(), key=f"deactivate_time_{trap_id}")
            confirm_deactivate = st.checkbox(
                "Close the current window (if open) and set this trap to Inactive",
                key=f"confirm_deactivate_{trap_id}",
            )
            if st.button("Deactivate trap", type="primary", key=f"commit_deactivate_{trap_id}", disabled=not confirm_deactivate):
                if not deactivate_reason.strip():
                    st.error("Enter a reason for deactivation.")
                else:
                    try:
                        effective = datetime.combine(deactivate_date, deactivate_time).replace(microsecond=0)
                        deactivate_trap(data, trap_id, effective, deactivate_reason.strip())
                        set_flash("success", f"{trap_id} deactivated.", ["Any open window was closed.", "No new window was started."])
                        go("setup")
                    except Exception as exc:
                        st.error(str(exc))
    else:
        with st.expander("Activate trap"):
            activate_reason = st.text_area("Reason for activation", key=f"activate_reason_{trap_id}")
            activate_date = st.date_input("Effective date", value=now().date(), key=f"activate_date_{trap_id}")
            activate_time = st.time_input("Effective time", value=now().time(), key=f"activate_time_{trap_id}")
            confirm_activate = st.checkbox(
                "Start a new monitoring window and set this trap to Active",
                key=f"confirm_activate_{trap_id}",
            )
            if st.button("Activate trap", type="primary", key=f"commit_activate_{trap_id}", disabled=not confirm_activate):
                if not activate_reason.strip():
                    st.error("Enter a reason for activation.")
                else:
                    try:
                        effective = datetime.combine(activate_date, activate_time).replace(microsecond=0)
                        activate_trap(data, trap_id, effective, activate_reason.strip())
                        set_flash("success", f"{trap_id} activated.", ["A new monitoring window was started."])
                        go("setup")
                    except Exception as exc:
                        st.error(str(exc))

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

            inactive_traps = data["Traps"][data["Traps"]["Status"] == "Inactive"].copy()
            if site_filter != "All sites":
                inactive_traps = inactive_traps[inactive_traps["Site ID"] == site_filter]
            with st.expander(f"Bulk activate traps ({len(inactive_traps)} inactive)"):
                # Trap activation window brief Phase 2 - same multi-select-plus-preview
                # shape as Window start corrections (Data & records), reused directly
                # rather than a new pattern: per-trap select + optional individual
                # time, a shared bulk time, a preview step, then one confirmed commit.
                if inactive_traps.empty:
                    st.caption("No inactive traps to activate" + (f" at {site_name(data, site_filter)}" if site_filter != "All sites" else "") + ".")
                else:
                    pending = st.session_state.get("bulkact_pending")
                    # UX-audit fix (2026-08-13): the selection checkboxes and time
                    # inputs used to stay live under an already-shown preview, so
                    # editing them after clicking "Preview" could silently commit
                    # something different from what the preview displayed. Locking
                    # everything below once a preview is pending means Cancel is the
                    # only way to change the selection - what's previewed is always
                    # exactly what gets committed.
                    locked = pending is not None
                    bulk_reason = st.text_area(
                        "Reason for these activations",
                        placeholder="e.g. New traps deployed for tomorrow's field pass.",
                        key="bulkact_reason",
                        disabled=locked,
                    )
                    st.markdown("#### Inactive traps")
                    selected_ids = []
                    individual_times = {}
                    for _, tr in inactive_traps.sort_values(["Site ID", "Trap ID"]).iterrows():
                        trap_id = tr["Trap ID"]
                        with app_card():
                            sel_col, info_col = st.columns([0.12, 0.88])
                            with sel_col:
                                selected = st.checkbox("Select", key=f"bulkact_select_{trap_id}", label_visibility="collapsed", disabled=locked)
                            with info_col:
                                st.markdown(f"**{trap_id}** · {site_name(data, tr['Site ID'])}")
                                st.caption(f"{tr['Product']} · {tr['Build Version']}")
                                use_individual = st.checkbox("Use a different time for this trap", key=f"bulkact_individual_toggle_{trap_id}", disabled=locked)
                                if use_individual:
                                    d_col, t_col = st.columns(2)
                                    with d_col:
                                        ind_date = st.date_input("Effective date", value=now().date(), key=f"bulkact_date_{trap_id}", disabled=locked)
                                    with t_col:
                                        ind_time = st.time_input("Effective time", value=now().time(), key=f"bulkact_time_{trap_id}", disabled=locked)
                                    individual_times[trap_id] = datetime.combine(ind_date, ind_time)
                        if selected:
                            selected_ids.append(trap_id)

                    st.markdown("#### Bulk apply")
                    if not selected_ids:
                        st.caption("Select one or more traps above to activate them together.")
                    else:
                        bulk_date = st.date_input("Shared effective date", value=now().date(), key="bulkact_bulk_date", disabled=locked)
                        bulk_time = st.time_input("Shared effective time", value=now().time(), key="bulkact_bulk_time", disabled=locked)
                        st.caption("Applies to every selected trap that doesn't have its own individual time set above.")
                        if st.button("Preview activation", key="bulkact_preview", disabled=locked):
                            st.session_state["bulkact_pending"] = {
                                "trap_ids": list(selected_ids),
                                "date": bulk_date,
                                "time": bulk_time,
                                "individual_times": dict(individual_times),
                                "reason": bulk_reason,
                            }
                            st.rerun()

                    if pending:
                        st.markdown("##### Confirm bulk activation")
                        pending_individual_times = pending["individual_times"]
                        shared_dt = datetime.combine(pending["date"], pending["time"])
                        preview_rows = [
                            {"Trap ID": trap_id, "Status": "Inactive → Active", "Effective time": human_dt(pending_individual_times.get(trap_id, shared_dt), include_year=True)}
                            for trap_id in pending["trap_ids"]
                        ]
                        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)
                        confirm_col, cancel_col = st.columns(2)
                        with confirm_col:
                            if st.button("Confirm bulk activate", type="primary", key="bulkact_confirm", disabled=not pending["reason"].strip()):
                                applied, skipped = [], []
                                for trap_id in pending["trap_ids"]:
                                    effective = pending_individual_times.get(trap_id, shared_dt)
                                    try:
                                        activate_trap(data, trap_id, effective, pending["reason"].strip(), commit=False)
                                        applied.append(trap_id)
                                    except ValueError as exc:
                                        skipped.append(f"{trap_id} ({exc})")
                                if applied:
                                    save_data(data)
                                st.session_state.pop("bulkact_pending", None)
                                detail = [f"{len(applied)} trap(s) activated: {', '.join(applied)}."] if applied else []
                                if skipped:
                                    detail.append(f"Skipped: {'; '.join(skipped)}.")
                                set_flash("success" if applied else "error", "Bulk activation applied." if applied else "No traps were activated.", detail)
                                st.rerun()
                        with cancel_col:
                            if st.button("Cancel", key="bulkact_cancel"):
                                st.session_state.pop("bulkact_pending", None)
                                st.rerun()

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
                        camera_text = tr["Camera ID"] or "None"
                        build_prefix = f"{tr['Product']} Build "
                        build_raw = str(tr["Build Version"] or "—")
                        build_text = build_raw[len(build_prefix):] if build_raw.startswith(build_prefix) else build_raw
                        st.markdown(
                            '<div class="shared-card-copy">'
                            f'<div class="shared-card-heading"><strong>{html.escape(str(trap_id))}</strong>{status_pill(str(tr["Status"]), "success" if tr["Status"] == "Active" else "none")}</div>'
                            f'<div class="shared-card-main">{html.escape(trap_location_label(tr))} · {html.escape(site_name(data, tr["Site ID"]))}</div>'
                            f'<div class="shared-card-meta">Build: {html.escape(build_text)} · Camera: {html.escape(str(camera_text))} · Route: {html.escape(str(tr["Route Order"] or "—"))}</div>'
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
                    if dep_date==now().date():
                        st.caption("Defaults to today — change this if the trap was actually deployed earlier.")
                    image=st.text_input("Setup image link",value=existing["Setup Image Link"] if existing is not None else "")
                    status=st.selectbox("Status",["Active","Inactive"],index=0 if existing is None or existing["Status"]=="Active" else 1,disabled=mode=="edit",help="Use Activate trap / Deactivate trap for an existing trap." if mode=="edit" else None)
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
                            old_status=data["Traps"].at[idx,"Status"]
                            if old_site!=site:
                                st.error("Use Move trap to change sites. Direct site changes are blocked so trial history is not rewritten.")
                            elif old_build!=build and open_window(data,trap_id) is not None:
                                st.error("Close the active test window before changing this trap's build.")
                            elif old_status!=status:
                                st.error("Use Activate trap / Deactivate trap to change status. Direct status changes are blocked so a trial window is never silently opened or left open.")
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
                        right_label_kind="success" if site_row["Status"] == "Active" else "none",
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

                    if ex["Status"] == "Inactive":
                        with st.expander("Permanently remove this site"):
                            st.warning("This permanently deletes every record tied to this site - traps, visits, test windows, checks, follow-up tasks and photos. This cannot be undone.")
                            removal_counts = site_code_link_counts(data, ex["Site ID"])
                            removal_trap_ids = data["Traps"][
                                data["Traps"]["Site ID"].astype(str).str.upper() == normalise_site_code(ex["Site ID"])
                            ]["Trap ID"].astype(str)
                            removal_counts["Checks"] = (
                                int(data["Checks"]["Trap ID"].astype(str).isin(removal_trap_ids).sum())
                                if not data["Checks"].empty else 0
                            )
                            st.markdown("**This will permanently remove**")
                            removal_preview_cols = st.columns(3)
                            removal_preview_items = [
                                ("Traps", removal_counts.get("Traps", 0)),
                                ("Visits", removal_counts.get("Visits", 0)),
                                ("Test windows", removal_counts.get("Windows", 0)),
                                ("Checks", removal_counts.get("Checks", 0)),
                                ("Follow-up tasks", removal_counts.get("Followups", 0)),
                                ("Photos", removal_counts.get("Photos", 0)),
                            ]
                            for position, (label, count) in enumerate(removal_preview_items):
                                removal_preview_cols[position % 3].metric(label, count)

                            removal_reason = st.text_area(
                                "Reason for removal",
                                placeholder="Why is this site being permanently removed?",
                                key=f"remove_site_reason_{ex['Site ID']}",
                            )
                            removal_confirm_name = st.text_input(
                                f"Type the site name ({ex['Site Name']}) to confirm",
                                key=f"remove_site_confirm_name_{ex['Site ID']}",
                            )
                            confirm_removal = st.checkbox(
                                "I understand this permanently deletes real trial history and cannot be undone",
                                key=f"confirm_site_removal_{ex['Site ID']}",
                            )
                            removal_ready = confirm_removal and removal_confirm_name.strip() == str(ex["Site Name"]).strip()
                            if st.button(
                                "Permanently remove site",
                                type="primary",
                                key=f"remove_site_button_{ex['Site ID']}",
                                disabled=not removal_ready,
                            ):
                                if not removal_reason.strip():
                                    st.error("Enter a reason for removing this site.")
                                else:
                                    try:
                                        removed_counts = permanently_remove_site(data, ex["Site ID"], removal_reason)
                                        total_removed = sum(removed_counts.values())
                                        site_name_removed = ex["Site Name"]
                                        st.session_state.pop("setup_site", None)
                                        st.session_state.pop("site_mode", None)
                                        set_flash(
                                            "success",
                                            f"{site_name_removed} permanently removed.",
                                            [
                                                f"{total_removed} linked record{'s' if total_removed != 1 else ''} deleted.",
                                                "A workbook backup and audit-log entry were created before removal.",
                                            ],
                                        )
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(f"Site was not removed: {exc}")

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
                    notes_raw = str(build_row["Notes"] or "No notes")
                    source_prefix = "Built from "
                    source_text = notes_raw[len(source_prefix):].rstrip(".") if notes_raw.startswith(source_prefix) else notes_raw
                    render_compact_card_content(
                        title=f"{product_code} Build {version}",
                        right_label=str(build_row["Build Status"]),
                        right_label_kind="success" if build_row["Build Status"] == "Current" else "none",
                        main_line=f"{active_traps} active trap{'s' if active_traps != 1 else ''}",
                        meta_line=f"First active: {first_active_text} · Source: {source_text}",
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
        ["Corrections", "Window start corrections", "Trial history", "Audit log", "Export and backup"],
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
            orphaned = missing_followup_windows(data)
            if not orphaned.empty:
                st.markdown("##### Recreate a missing follow-up")
                st.caption("Windows whose finding or camera assignment genuinely warrants a review but that currently have no linked follow-up task - most likely one was removed and needs restoring.")
                orphan_options = orphaned["Window ID"].tolist()
                orphan_selected = st.selectbox(
                    "Select window needing a follow-up",
                    orphan_options,
                    format_func=lambda wid: (lambda r: f"{r['Trap ID']} · {site_name(data, r['Site ID'])} · {r['Finding At Close']} · {wid}")(orphaned[orphaned["Window ID"] == wid].iloc[0]),
                    key="recreate_followup_window",
                )
                orphan_row = orphaned[orphaned["Window ID"] == orphan_selected].iloc[0]
                workflow_context([
                    ("Trap", orphan_row["Trap ID"]),
                    ("Site", site_name(data, orphan_row["Site ID"])),
                    ("Bag ID", orphan_row["Bag ID"]),
                    ("Finding at close", orphan_row["Finding At Close"]),
                    ("Final humane kill", orphan_row["Final Humane Kill"]),
                    ("Review status", orphan_row["Review Status"]),
                ])
                types_needed = []
                assessable_orphan = orphan_row["Finding At Close"] not in ["Trap missing", "Unable to check"]
                if orphan_row["Finding At Close"] == "Dead animal found":
                    types_needed.append("Necropsy review")
                if assessable_orphan and orphan_row["Camera Assigned"] == "Yes":
                    types_needed.append("Camera review")
                recreate_type = st.selectbox(
                    "Follow-up type to recreate", types_needed, key=f"recreate_followup_type_{orphan_selected}"
                ) if types_needed else None
                recreate_reason = st.text_area("Reason for recreating", key=f"recreate_followup_reason_{orphan_selected}")
                if st.button(
                    "Recreate follow-up",
                    type="primary",
                    key=f"recreate_followup_btn_{orphan_selected}",
                    disabled=not recreate_type,
                ):
                    if not recreate_reason.strip():
                        st.error("Enter a reason for recreating the follow-up.")
                    else:
                        try:
                            recreate_followup(data, orphan_selected, recreate_type, recreate_reason)
                            set_flash(
                                "success",
                                "Follow-up recreated.",
                                [
                                    f"{recreate_type} recreated for {orphan_row['Trap ID']}.",
                                    "It now appears in the normal Follow-ups list to complete.",
                                    "The recreation is recorded in the audit log, referencing the removal reason it followed.",
                                ],
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                st.divider()
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
                timestamp_inputs = {}
                if record_type == "Camera evidence":
                    editable = {
                        "Finding At Close": FINDINGS,
                        "Evidence Usable": ["Yes", "No", "Pending"],
                        "Target Present": ["Yes", "No", "Unclear", "Pending"],
                        "Interaction Level": ["Single interaction", "Repeated interaction", "Heavy / repeated interaction", "Not applicable", "Unclear", "Pending"],
                        "Entered Strike Area": ["Yes", "No", "Unclear", "Not applicable", "Pending"],
                        "Trap Activated": ["Yes", "No", "Unclear", "Pending"],
                        "Kill Confirmed": ["Yes", "No", "Unclear", "Pending"],
                        "Video Assessment": ["Humane", "Not humane", "Unclear", "No usable video", "Not applicable", "Pending"],
                    }
                    timestamp_fields = [
                        ("First Interaction Time", "First target interaction"),
                        ("Trigger Time", "First activation"),
                        ("Kill Time", "Kill"),
                    ]
                    window_start = parse_dt(row["Start Time"])
                    window_end = parse_dt(row["End Time"])
                    min_evidence_date = window_start.date() if window_start else None
                    max_evidence_date = window_end.date() if window_end else None
                    changed = {}
                    timestamp_inputs = {}
                    with st.form(f"correct_camera_evidence_{selected_id}"):
                        for field, choices in editable.items():
                            current = str(row[field])
                            index = choices.index(current) if current in choices else 0
                            changed[field] = st.selectbox(field, choices, index=index, key=f"corr_{field}_{selected_id}")
                        st.markdown("##### Event timestamps")
                        st.caption("Record when events occurred in the footage. Leave a date blank to leave that timestamp unchanged.")
                        for field, label in timestamp_fields:
                            current_dt = parse_dt(row[field])
                            date_col, time_col = st.columns(2)
                            with date_col:
                                ts_date = st.date_input(
                                    f"{label} date",
                                    value=current_dt.date() if current_dt else None,
                                    min_value=min_evidence_date,
                                    max_value=max_evidence_date,
                                    key=f"corr_{field}_date_{selected_id}",
                                )
                            with time_col:
                                ts_time = st.time_input(
                                    f"{label} time",
                                    value=current_dt.time() if current_dt else None,
                                    key=f"corr_{field}_time_{selected_id}",
                                )
                            timestamp_inputs[field] = (ts_date, ts_time)
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
                            for field, (ts_date, ts_time) in timestamp_inputs.items():
                                if ts_date is None or ts_time is None:
                                    continue
                                old_value = str(data["Windows"].at[idx, field])
                                new_value = dtstr(datetime.combine(ts_date, ts_time))
                                if new_value != old_value:
                                    data["Windows"].at[idx, field] = new_value
                                    audit_rows.append([make_id("CHG"), dtstr(), record_type, selected_id, field, old_value, new_value, reason.strip()])
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
                    editable = {
                        "Necropsy Status": ["Complete", "Not completed", "Unable to assess", "Not started"],
                        "Necropsy Assessment": ["Supports humane kill", "Does not support humane kill", "Unclear", "Not assessable", "Pending"],
                        "Species": SPECIES,
                        "Rat Type": RAT_TYPES,
                        "Animal Weight Range": weight_ranges_for_species(row["Species"]) + [""],
                        "Final Humane Kill": ["Yes", "No", "Unclear", "Not assessable", "Pending"],
                    }
                    changed = {}
                    st.markdown("##### Photos")
                    st.caption("Attach necropsy photos for the trial record. Same upload behaviour as a necropsy review task - select multiple, each uploads independently.")
                    photo_gate = render_correction_necropsy_photo_capture(selected_id, str(row["Trap ID"]), str(row["Site ID"]))
                    photo_blocked = bool(photo_gate.get("expected_count", 0) and not photo_gate.get("ready"))
                    if photo_gate.get("expected_count", 0):
                        if photo_gate.get("manual_failure_count", 0):
                            count = int(photo_gate["manual_failure_count"])
                            st.caption(f"{count} photo{'s' if count != 1 else ''} could not upload")
                        elif photo_gate.get("ready"):
                            st.caption(f"{photo_gate['file_count']} photo{'s' if photo_gate['file_count'] != 1 else ''} saved")
                        else:
                            remaining = max(1, photo_gate.get("expected_count", 0) - photo_gate.get("file_count", 0))
                            st.caption(f"Uploading {remaining} photo{'s' if remaining != 1 else ''}…")
                    for field, choices in editable.items():
                        current = str(row[field])
                        index = choices.index(current) if current in choices else 0
                        changed[field] = st.selectbox(field, choices, index=index, key=f"corr_{field}_{selected_id}")
                    reason = st.text_area("Correction reason", key=f"corr_reason_{selected_id}")
                    save_label = "Please wait" if photo_blocked else "Save correction"
                    save_correction = st.button(save_label, type="primary", key=f"correct_necropsy_evidence_save_{selected_id}", disabled=photo_blocked)
                    if save_correction:
                        # UX-audit fix (2026-08-13): this form used to let a correction save a
                        # necropsy result the original review task would have rejected outright
                        # (e.g. "Supports humane kill" paired with Final Humane Kill = No) - same
                        # validator the review task itself calls, so a correction can't reintroduce
                        # exactly the kind of inconsistency this tool exists to fix.
                        necropsy_errors = necropsy_consistency_errors(
                            changed["Necropsy Status"], changed["Necropsy Assessment"], changed["Final Humane Kill"]
                        )
                        if not reason.strip():
                            st.error("Enter a correction reason before saving.")
                        elif necropsy_errors:
                            st.error("Please correct the necropsy result:\n\n" + "\n".join(f"- {err}" for err in necropsy_errors))
                        else:
                            expected_photo_count = int(photo_gate.get("expected_count", 0))
                            original_data = {name: frame.copy(deep=True) for name, frame in data.items()}
                            staged = {name: frame.copy(deep=True) for name, frame in data.items()}
                            audit_rows = []
                            for field, new_value in changed.items():
                                old_value = str(staged["Windows"].at[idx, field])
                                if str(new_value) != old_value:
                                    staged["Windows"].at[idx, field] = new_value
                                    audit_rows.append([make_id("CHG"), dtstr(), record_type, selected_id, field, old_value, str(new_value), reason.strip()])
                            if not audit_rows and not expected_photo_count:
                                st.info("No values changed.")
                            else:
                                recalculate_window(staged, idx)
                                refresh_review_status(staged, selected_id)
                                if audit_rows:
                                    staged["Audit Log"] = pd.concat([staged["Audit Log"], pd.DataFrame(audit_rows, columns=SHEETS["Audit Log"])], ignore_index=True)

                                def _verify_correction_persisted(reloaded):
                                    return {}

                                commit_staged_records_with_photos(
                                    data=data,
                                    staged=staged,
                                    original_data=original_data,
                                    photo_gate=photo_gate,
                                    expected_photo_count=expected_photo_count,
                                    record_id=photo_gate["follow_up_id"],
                                    photos_id_column="Follow-up ID",
                                    verify_persisted=_verify_correction_persisted,
                                    log_prefix="correction_necropsy",
                                    log_fields={"window_id": selected_id, "trap_id": str(row["Trap ID"])},
                                    record_noun="correction",
                                    record_description="necropsy correction or photo record",
                                )
                                set_flash(
                                    "success", "Correction saved.",
                                    [f"{len(audit_rows)} field change(s) were applied." if audit_rows else "No field values changed.",
                                     f"{expected_photo_count} photo(s) attached." if expected_photo_count else "No new photos attached.",
                                     "Next: make another correction or return to the relevant record."],
                                )
                                st.rerun()
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
                        # UX-audit fix (2026-08-13): correcting a check's Finding used to leave
                        # the Window it closed untouched - Trial Performance and the Kills sheet
                        # are both Windows-driven, so the correction silently didn't move the
                        # numbers it exists to fix. Propagate to the window this check closed,
                        # same as a fresh check does via close_window(), and recompute/re-review it.
                        window_id=str(row["Window Closed"])
                        if window_id and str(finding)!=str(row["Finding"]):
                            window_matches=data["Windows"].index[data["Windows"]["Window ID"]==window_id].tolist()
                            if window_matches:
                                widx=window_matches[0]
                                old_window_finding=str(data["Windows"].at[widx,"Finding At Close"])
                                if old_window_finding!=str(finding):
                                    data["Windows"].at[widx,"Finding At Close"]=finding
                                    audit_rows.append([make_id("CHG"),dtstr(),record_type,window_id,"Finding At Close",old_window_finding,str(finding),reason.strip()])
                                recalculate_window(data,widx)
                                refresh_review_status(data,window_id)
                        if audit_rows:
                            data["Audit Log"] = pd.concat([data["Audit Log"], pd.DataFrame(audit_rows, columns=SHEETS["Audit Log"])], ignore_index=True)
                            save_data(data); set_flash("success","Correction saved.",[f"{len(audit_rows)} field change(s) were applied.","The audit log retained the previous and corrected values.","Next: make another correction or return to the relevant record."]); st.rerun()
                        else: st.info("No values changed.")

    if active_data_section == "Window start corrections":
        helper("A trap's earliest test window can end up with a Start Time later than when the trap was truly deployed, if the trap was physically live in the field before being added to the app. That blocks entering real footage timestamps from before the window's recorded start.")
        st.write("Correct a flagged trap's earliest window individually, or select several traps and apply one confirmed date and time to all of them at once.")

        r1_candidates = suspect_earliest_window_candidates(data, "R1")
        if not r1_candidates:
            st.success("No R1 trap's earliest window currently looks suspect.")
        else:
            r1_trap_ids = data["Traps"][data["Traps"]["Product"] == "R1"]["Trap ID"]
            open_camera_reviews = data["Followups"][
                (data["Followups"]["Status"] == "Open")
                & (data["Followups"]["Follow-up Type"] == "Camera review")
                & (data["Followups"]["Trap ID"].isin(r1_trap_ids))
            ]
            st.caption(f"{len(r1_candidates)} R1 trap(s) flagged with a suspect earliest-window start · {len(open_camera_reviews)} open camera review task(s) exist for R1 traps. If these counts don't roughly line up, some cases may be missing from this list.")

            reason = st.text_area(
                "Reason for these corrections",
                placeholder="e.g. Confirmed true deployment date against field records and camera footage timestamps.",
                key="winfix_reason",
            )

            st.markdown("#### Flagged traps")
            selected_ids = []
            for c in r1_candidates:
                with app_card():
                    sel_col, info_col = st.columns([0.08, 0.92])
                    with sel_col:
                        selected = st.checkbox(
                            "Select",
                            key=f"winfix_select_{c['Trap ID']}",
                            label_visibility="collapsed",
                            disabled=not c["Eligible"],
                        )
                    with info_col:
                        st.markdown(f"**{c['Trap ID']}** · {site_name(data, c['Site ID'])}")
                        st.caption(f"Window {c['Window ID']} · Review status: {c['Review Status']}")
                        st.write(f"Current earliest-window start: {human_dt(c['Current Start'], include_year=True)}")
                        st.write(f"Trap's Deployment Start: {human_dt(c['Deployment Start'], include_year=True) if c['Deployment Start'] else 'Not set'}")
                        if not c["Eligible"]:
                            st.warning("This window's review has already been completed — it can no longer be corrected through this tool.")
                        else:
                            d_col, t_col = st.columns(2)
                            with d_col:
                                new_date = st.date_input("True deployment date", value=c["Current Start"].date(), key=f"winfix_date_{c['Trap ID']}")
                            with t_col:
                                new_time = st.time_input("True deployment time", value=c["Current Start"].time(), key=f"winfix_time_{c['Trap ID']}")
                            if st.button("Apply this trap", key=f"winfix_apply_{c['Trap ID']}"):
                                if not reason.strip():
                                    st.error("Enter a reason before applying a correction.")
                                else:
                                    try:
                                        changed = correct_window_start(data, c["Window ID"], datetime.combine(new_date, new_time), reason.strip())
                                        if changed:
                                            save_data(data)
                                            set_flash("success", f"{c['Trap ID']} corrected.", [f"Window {c['Window ID']} Start Time updated.", "Recorded in the audit log."])
                                        else:
                                            st.info("No change — the entered date and time match the current value.")
                                        st.rerun()
                                    except ValueError as exc:
                                        st.error(str(exc))
                if selected:
                    selected_ids.append(c["Trap ID"])

            st.markdown("#### Bulk apply to selected traps")
            if not selected_ids:
                st.caption("Select one or more traps above to apply one date and time to all of them.")
            else:
                bulk_date = st.date_input("Shared true deployment date", key="winfix_bulk_date")
                bulk_time = st.time_input("Shared true deployment time", key="winfix_bulk_time")
                if st.button("Preview bulk apply", key="winfix_bulk_preview"):
                    st.session_state["winfix_bulk_pending"] = {
                        "trap_ids": list(selected_ids),
                        "date": bulk_date,
                        "time": bulk_time,
                    }
                    st.rerun()

            pending = st.session_state.get("winfix_bulk_pending")
            if pending:
                st.markdown("##### Confirm bulk correction")
                new_dt = datetime.combine(pending["date"], pending["time"])
                preview_rows = [
                    {"Trap ID": c["Trap ID"], "Old Start": human_dt(c["Current Start"], include_year=True), "New Start": human_dt(new_dt, include_year=True)}
                    for c in r1_candidates if c["Trap ID"] in pending["trap_ids"]
                ]
                st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)
                confirm_col, cancel_col = st.columns(2)
                with confirm_col:
                    if st.button("Confirm bulk apply", type="primary", key="winfix_bulk_confirm", disabled=not reason.strip()):
                        applied, skipped = [], []
                        for c in r1_candidates:
                            if c["Trap ID"] not in pending["trap_ids"]:
                                continue
                            try:
                                if correct_window_start(data, c["Window ID"], new_dt, reason.strip()):
                                    applied.append(c["Trap ID"])
                                else:
                                    skipped.append(f"{c['Trap ID']} (no change)")
                            except ValueError as exc:
                                skipped.append(f"{c['Trap ID']} ({exc})")
                        if applied:
                            save_data(data)
                        st.session_state.pop("winfix_bulk_pending", None)
                        detail = [f"{len(applied)} trap(s) corrected: {', '.join(applied)}."] if applied else []
                        if skipped:
                            detail.append(f"Skipped: {'; '.join(skipped)}.")
                        set_flash("success" if applied else "error", "Bulk correction applied." if applied else "No traps were corrected.", detail)
                        st.rerun()
                with cancel_col:
                    if st.button("Cancel", key="winfix_bulk_cancel"):
                        st.session_state.pop("winfix_bulk_pending", None)
                        st.rerun()

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
