from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, Optional

from PIL import Image, ImageOps

PHOTO_SCHEMA_VERSION = 1
PENDING_DIR_NAME = ".pending_photos"
LOG_FILE_NAME = "photo_upload_log.jsonl"
DEFAULT_TTL_HOURS = 72
PHOTO_ID_RE = re.compile(r"^PHOTO-[A-Za-z0-9_-]{8,96}$")


class PhotoPermanentError(ValueError):
    """The same prepared payload should not be retried automatically."""


class PhotoTransientError(IOError):
    """A retry may succeed without changing the selected photo."""


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def deterministic_check_id(visit_id: str, trap_id: str) -> str:
    token = hashlib.sha256(f"{visit_id}|{trap_id}".encode("utf-8")).hexdigest()[:20].upper()
    return f"CHK-{token}"


def _safe_token(value: str, fallback: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "").strip())
    return token[:120] or fallback


def _safe_relative_path(value: str) -> Optional[Path]:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise PhotoPermanentError("Stored photo path is invalid.")
    return candidate


def pending_root(data_root: Path) -> Path:
    return Path(data_root) / PENDING_DIR_NAME


def transaction_dir(data_root: Path, check_id: str) -> Path:
    return pending_root(data_root) / _safe_token(check_id, "check")


def manifest_path(data_root: Path, check_id: str) -> Path:
    return transaction_dir(data_root, check_id) / "manifest.json"


def _pending_image_path(data_root: Path, check_id: str, photo_id: str) -> Path:
    return transaction_dir(data_root, check_id) / f"{_safe_token(photo_id, 'photo')}.jpg"


def _final_image_path(
    data_root: Path,
    check_id: str,
    site_id: str,
    bag_id: str,
    trap_id: str,
    photo_id: str,
) -> Path:
    folder = Path(data_root) / "evidence" / _safe_token(site_id, "site") / _safe_token(bag_id or trap_id, "trap")
    return folder / f"{_safe_token(check_id, 'check')}_{_safe_token(photo_id, 'photo')}.jpg"


def _log(data_root: Path, event: str, **fields) -> None:
    try:
        Path(data_root).mkdir(parents=True, exist_ok=True)
        record = {"timestamp": utc_now_text(), "event": event, **fields}
        with (Path(data_root) / LOG_FILE_NAME).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        # Logging must never break field data capture.
        pass


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise PhotoTransientError("Photo state could not be stored.") from exc


def load_manifest(data_root: Path, check_id: str) -> Optional[dict]:
    path = manifest_path(data_root, check_id)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PhotoTransientError("Saved photo state could not be read.") from exc
    if not isinstance(value, dict) or value.get("schema_version") != PHOTO_SCHEMA_VERSION:
        raise PhotoPermanentError("Saved photo state is not compatible with this release.")
    return value


def _new_manifest(context: dict) -> dict:
    return {
        "schema_version": PHOTO_SCHEMA_VERSION,
        "check_id": context["check_id"],
        "visit_id": context["visit_id"],
        "trap_id": context["trap_id"],
        "site_id": context["site_id"],
        "bag_id": context.get("bag_id", ""),
        "window_id": context["window_id"],
        "created_at": utc_now_text(),
        "updated_at": utc_now_text(),
        "expected_photo_ids": [],
        "selections": {},
        "photos": {},
        "failures": {},
        "removed_photo_ids": [],
    }


def _validate_context(manifest: dict, context: dict) -> None:
    for key in ("check_id", "visit_id", "trap_id", "site_id", "window_id"):
        if str(manifest.get(key, "")) != str(context.get(key, "")):
            raise PhotoPermanentError("Pending photo state does not match this trap check.")
    existing_bag = str(manifest.get("bag_id", ""))
    incoming_bag = str(context.get("bag_id", ""))
    if existing_bag and incoming_bag and existing_bag != incoming_bag:
        raise PhotoPermanentError("Pending photo state belongs to a different bag ID.")


def ensure_manifest(data_root: Path, context: dict) -> dict:
    manifest = load_manifest(data_root, context["check_id"])
    if manifest is None:
        manifest = _new_manifest(context)
    else:
        _validate_context(manifest, context)
        if not manifest.get("bag_id") and context.get("bag_id"):
            manifest["bag_id"] = context["bag_id"]
    return manifest


def save_manifest(data_root: Path, manifest: dict) -> None:
    manifest["updated_at"] = utc_now_text()
    _atomic_write_json(manifest_path(data_root, manifest["check_id"]), manifest)


def recover_bag_id(data_root: Path, check_id: str, visit_id: str, trap_id: str) -> str:
    manifest = load_manifest(data_root, check_id)
    if not manifest:
        return ""
    if str(manifest.get("visit_id")) != str(visit_id) or str(manifest.get("trap_id")) != str(trap_id):
        return ""
    return str(manifest.get("bag_id", ""))


def add_expected_photos(data_root: Path, context: dict, selections: Iterable[dict]) -> dict:
    manifest = ensure_manifest(data_root, context)
    expected = list(manifest.get("expected_photo_ids", []))
    removed = set(str(x) for x in manifest.get("removed_photo_ids", []))
    selection_map = dict(manifest.get("selections", {}))
    for item in selections:
        photo_id = str(item.get("photo_id", "")).strip()
        if not PHOTO_ID_RE.fullmatch(photo_id):
            raise PhotoPermanentError("Selected photo ID is invalid.")
        if photo_id in removed:
            continue
        if photo_id not in expected:
            expected.append(photo_id)
        selection_map[photo_id] = {"name": str(item.get("name") or "photo.jpg")[:240]}
    manifest["expected_photo_ids"] = expected
    manifest["selections"] = selection_map
    save_manifest(data_root, manifest)
    _log(data_root, "selection_recorded", check_id=context["check_id"], trap_id=context["trap_id"], expected_count=len(expected))
    return manifest


def decode_prepared_jpeg(data_url: str) -> bytes:
    if not str(data_url).startswith("data:image/jpeg;base64,"):
        raise PhotoPermanentError("Prepared photo is not a JPEG image.")
    try:
        return base64.b64decode(str(data_url).split(",", 1)[1], validate=True)
    except Exception as exc:
        raise PhotoPermanentError("Prepared photo data is incomplete.") from exc


def validate_prepared_photo(raw_bytes: bytes, width: int, height: int, max_saved_bytes: int) -> tuple[int, int]:
    if not raw_bytes:
        raise PhotoPermanentError("Prepared photo is empty.")
    if len(raw_bytes) > int(max_saved_bytes):
        raise PhotoPermanentError("Prepared photo is too large.")
    try:
        image = Image.open(BytesIO(raw_bytes))
        image.verify()
        image = Image.open(BytesIO(raw_bytes))
        if image.format != "JPEG":
            raise PhotoPermanentError("Prepared photo is not a JPEG image.")
        actual_width, actual_height = image.size
        if max(actual_width, actual_height) > 2000:
            raise PhotoPermanentError("Prepared photo dimensions are too large.")
        if width and height and (actual_width, actual_height) != (int(width), int(height)):
            raise PhotoPermanentError("Prepared photo dimensions do not match the upload metadata.")
        return actual_width, actual_height
    except PhotoPermanentError:
        raise
    except Exception as exc:
        raise PhotoPermanentError("Prepared photo could not be verified.") from exc


def preview_data_url(raw_bytes: bytes) -> str:
    try:
        image = Image.open(BytesIO(raw_bytes))
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((320, 320), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=65, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception as exc:
        raise PhotoPermanentError("Stored photo preview could not be created.") from exc


def _write_file_once(path: Path, raw_bytes: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.pending"
    try:
        temp.write_bytes(raw_bytes)
        if temp.stat().st_size != len(raw_bytes):
            raise OSError("temporary photo size mismatch")
        os.replace(temp, path)
        if not path.exists() or path.stat().st_size != len(raw_bytes):
            raise OSError("stored photo size mismatch")
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise PhotoTransientError("Photo storage is temporarily unavailable.") from exc


def record_failure(
    data_root: Path,
    context: dict,
    photo_id: str,
    *,
    retryable: bool,
    error_code: str,
    user_error: str,
    manual_required: bool,
    name: str = "photo.jpg",
    attempt: int = 0,
    detail: str = "",
) -> dict:
    manifest = ensure_manifest(data_root, context)
    if photo_id not in manifest.get("expected_photo_ids", []):
        manifest["expected_photo_ids"].append(photo_id)
    manifest.setdefault("selections", {})[photo_id] = {"name": str(name or "photo.jpg")[:240]}
    manifest.setdefault("failures", {})[photo_id] = {
        "retryable": bool(retryable),
        "error_code": str(error_code),
        "user_error": str(user_error),
        "manual_required": bool(manual_required),
        "attempt": int(attempt or 0),
        "updated_at": utc_now_text(),
    }
    save_manifest(data_root, manifest)
    _log(
        data_root,
        "upload_failed",
        check_id=context["check_id"], trap_id=context["trap_id"], photo_id=photo_id,
        attempt=int(attempt or 0), retryable=bool(retryable), error_code=error_code,
        detail=str(detail)[:500],
    )
    return manifest


def mark_retry_started(data_root: Path, context: dict, photo_id: str) -> None:
    manifest = ensure_manifest(data_root, context)
    failure = manifest.setdefault("failures", {}).get(photo_id)
    if failure:
        failure["manual_required"] = False
        failure["updated_at"] = utc_now_text()
        save_manifest(data_root, manifest)


def store_photo(data_root: Path, context: dict, payload: dict, max_saved_bytes: int) -> dict:
    photo_id = str(payload.get("photo_id", "")).strip()
    if not PHOTO_ID_RE.fullmatch(photo_id):
        raise PhotoPermanentError("Photo ID is invalid.")
    manifest = ensure_manifest(data_root, context)
    removed = set(str(x) for x in manifest.get("removed_photo_ids", []))
    if photo_id in removed:
        return {"status": "removed", "photo_id": photo_id}
    if photo_id not in manifest.get("expected_photo_ids", []):
        manifest["expected_photo_ids"].append(photo_id)
    manifest.setdefault("selections", {})[photo_id] = {"name": str(payload.get("name") or "photo.jpg")[:240]}

    raw_bytes = decode_prepared_jpeg(payload.get("data_url", ""))
    actual_width, actual_height = validate_prepared_photo(
        raw_bytes,
        int(payload.get("width") or 0),
        int(payload.get("height") or 0),
        max_saved_bytes,
    )
    digest = hashlib.sha256(raw_bytes).hexdigest()
    existing = manifest.setdefault("photos", {}).get(photo_id)
    path = _pending_image_path(data_root, context["check_id"], photo_id)

    if existing:
        if existing.get("sha256") != digest:
            raise PhotoPermanentError("A different image already uses this photo ID.")
        if path.exists() and path.stat().st_size == len(raw_bytes):
            validate_prepared_photo(path.read_bytes(), actual_width, actual_height, max_saved_bytes)
            manifest.setdefault("failures", {}).pop(photo_id, None)
            save_manifest(data_root, manifest)
            _log(data_root, "upload_idempotent", check_id=context["check_id"], trap_id=context["trap_id"], photo_id=photo_id, attempt=int(payload.get("attempt") or 0))
            return existing

    _write_file_once(path, raw_bytes)
    relative = path.relative_to(Path(data_root)).as_posix()
    row = {
        "Photo ID": photo_id,
        "Check ID": context["check_id"],
        "Window ID": context["window_id"],
        "Trap ID": context["trap_id"],
        "Site ID": context["site_id"],
        "Bag ID": context.get("bag_id", ""),
        "Capture Time": str(payload.get("captured_time") or utc_now_text()),
        "Photo Type": "Check evidence",
        "File Path": relative,
        "Notes": "",
    }
    item = {
        "row": row,
        "sha256": digest,
        "width": actual_width,
        "height": actual_height,
        "original_size": int(payload.get("original_size") or 0),
        "prepared_size": len(raw_bytes),
        "preview": preview_data_url(raw_bytes),
        "saved_at": utc_now_text(),
    }
    manifest.setdefault("photos", {})[photo_id] = item
    manifest.setdefault("failures", {}).pop(photo_id, None)
    save_manifest(data_root, manifest)
    _log(
        data_root,
        "upload_saved",
        check_id=context["check_id"], trap_id=context["trap_id"], photo_id=photo_id,
        attempt=int(payload.get("attempt") or 0), original_size=int(payload.get("original_size") or 0),
        prepared_size=len(raw_bytes), width=actual_width, height=actual_height,
    )
    return item


def remove_photo(data_root: Path, context: dict, photo_id: str) -> dict:
    manifest = ensure_manifest(data_root, context)
    photo_id = str(photo_id)
    manifest["expected_photo_ids"] = [x for x in manifest.get("expected_photo_ids", []) if str(x) != photo_id]
    manifest.setdefault("selections", {}).pop(photo_id, None)
    manifest.setdefault("failures", {}).pop(photo_id, None)
    manifest.setdefault("photos", {}).pop(photo_id, None)
    removed = list(dict.fromkeys([*manifest.get("removed_photo_ids", []), photo_id]))
    manifest["removed_photo_ids"] = removed
    _pending_image_path(data_root, context["check_id"], photo_id).unlink(missing_ok=True)
    save_manifest(data_root, manifest)
    _log(data_root, "photo_removed", check_id=context["check_id"], trap_id=context["trap_id"], photo_id=photo_id)
    return manifest


def verify_pending(data_root: Path, context: dict, max_saved_bytes: int) -> dict:
    manifest = load_manifest(data_root, context["check_id"])
    if manifest is None:
        return {
            "expected_count": 0, "file_count": 0, "row_count": 0,
            "ready": True, "errors": [], "failed_count": 0,
            "manual_failure_count": 0, "photos": [], "removed_ids": [],
        }
    _validate_context(manifest, context)
    expected = list(dict.fromkeys(str(x) for x in manifest.get("expected_photo_ids", [])))
    photos = manifest.get("photos", {})
    failures = manifest.get("failures", {})
    errors = []
    valid_ids = []
    durable_rows = []

    for photo_id in expected:
        item = photos.get(photo_id)
        if not item:
            continue
        row = item.get("row", {})
        required_values = {
            "Photo ID": photo_id,
            "Check ID": context["check_id"],
            "Window ID": context["window_id"],
            "Trap ID": context["trap_id"],
            "Site ID": context["site_id"],
            "Bag ID": context.get("bag_id", ""),
        }
        mismatch = [key for key, value in required_values.items() if str(row.get(key, "")) != str(value)]
        if mismatch:
            errors.append(f"{photo_id}: pending Photos row mismatch")
            continue
        rel = _safe_relative_path(row.get("File Path", ""))
        path = Path(data_root) / rel if rel else None
        if not path or not path.exists() or path.stat().st_size <= 0:
            errors.append(f"{photo_id}: stored file missing")
            continue
        try:
            raw = path.read_bytes()
            validate_prepared_photo(raw, int(item.get("width") or 0), int(item.get("height") or 0), max_saved_bytes)
            if hashlib.sha256(raw).hexdigest() != item.get("sha256"):
                raise PhotoPermanentError("hash mismatch")
        except Exception:
            errors.append(f"{photo_id}: stored file invalid")
            continue
        valid_ids.append(photo_id)
        durable_rows.append(row)

    extra_rows = [photo_id for photo_id in photos if str(photo_id) not in set(expected)]
    if extra_rows:
        errors.append("Unexpected pending Photos rows are present.")

    row_ids = [str(row.get("Photo ID", "")) for row in durable_rows]
    if len(row_ids) != len(set(row_ids)):
        errors.append("Duplicate pending Photos rows are present.")

    manual_failures = [
        photo_id for photo_id in expected
        if photo_id in failures and bool(failures[photo_id].get("manual_required"))
    ]
    ui_photos = []
    for photo_id in expected:
        if photo_id in photos and photo_id in valid_ids:
            item = photos[photo_id]
            ui_photos.append({
                "photo_id": photo_id,
                "name": manifest.get("selections", {}).get(photo_id, {}).get("name", "photo.jpg"),
                "status": "saved",
                "error": "",
                "retryable": False,
                "manual_required": False,
                "preview": item.get("preview", ""),
            })
        elif photo_id in failures:
            failure = failures[photo_id]
            ui_photos.append({
                "photo_id": photo_id,
                "name": manifest.get("selections", {}).get(photo_id, {}).get("name", "photo.jpg"),
                "status": "failed",
                "error": str(failure.get("user_error") or "Upload failed"),
                "retryable": bool(failure.get("retryable")),
                "manual_required": bool(failure.get("manual_required")),
                "preview": "",
            })
        else:
            ui_photos.append({
                "photo_id": photo_id,
                "name": manifest.get("selections", {}).get(photo_id, {}).get("name", "photo.jpg"),
                "status": "pending",
                "error": "",
                "retryable": False,
                "manual_required": False,
                "preview": "",
            })

    ready = not errors and len(expected) == len(valid_ids) == len(durable_rows)
    result = {
        "expected_count": len(expected),
        "file_count": len(valid_ids),
        "row_count": len(durable_rows),
        "ready": ready,
        "errors": errors,
        "failed_count": len([p for p in expected if p in failures]),
        "manual_failure_count": len(manual_failures),
        "photos": ui_photos,
        "removed_ids": list(manifest.get("removed_photo_ids", [])),
        "rows": durable_rows,
    }
    _log(
        data_root,
        "verification",
        check_id=context["check_id"], trap_id=context["trap_id"],
        expected_count=result["expected_count"], file_count=result["file_count"], row_count=result["row_count"], ready=result["ready"],
    )
    return result


def build_finalisation_plan(data_root: Path, context: dict, max_saved_bytes: int) -> dict:
    verification = verify_pending(data_root, context, max_saved_bytes)
    if not verification["ready"]:
        raise PhotoTransientError("Selected photos are not completely verified.")
    moves = []
    rows = []
    for row in verification.get("rows", []):
        photo_id = str(row["Photo ID"])
        source_rel = _safe_relative_path(row["File Path"])
        source = Path(data_root) / source_rel
        destination = _final_image_path(
            data_root, context["check_id"], context["site_id"], context.get("bag_id", ""), context["trap_id"], photo_id
        )
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != hashlib.sha256(source.read_bytes()).hexdigest():
                raise PhotoPermanentError("A different final photo already exists for this photo ID.")
        moves.append((source, destination))
        final_row = dict(row)
        final_row["File Path"] = destination.relative_to(Path(data_root)).as_posix()
        rows.append(final_row)
    return {"verification": verification, "moves": moves, "rows": rows}


def apply_final_copies(plan: dict) -> list[tuple[Path, Path, bool]]:
    """Copy verified pending photos into final evidence paths without removing recovery originals.

    Keeping the pending source until the workbook commit is verified closes the crash window
    where a file could otherwise be moved out of the pending transaction before its Photos
    row/check record is durable. The boolean marks destinations created by this call.
    """
    completed = []
    try:
        for source, destination in plan.get("moves", []):
            if not source.exists() or source.stat().st_size <= 0:
                raise PhotoTransientError("Pending photo file disappeared before final save.")
            source_bytes = source.read_bytes()
            source_hash = hashlib.sha256(source_bytes).hexdigest()
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.stat().st_size <= 0 or hashlib.sha256(destination.read_bytes()).hexdigest() != source_hash:
                    raise PhotoPermanentError("A different final photo already exists for this photo ID.")
                completed.append((source, destination, False))
                continue

            temp = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.pending"
            try:
                temp.write_bytes(source_bytes)
                if temp.stat().st_size != len(source_bytes):
                    raise OSError("temporary final photo size mismatch")
                os.replace(temp, destination)
                if destination.stat().st_size != len(source_bytes):
                    raise OSError("final photo size mismatch")
                if hashlib.sha256(destination.read_bytes()).hexdigest() != source_hash:
                    raise OSError("final photo hash mismatch")
            except OSError as exc:
                temp.unlink(missing_ok=True)
                raise PhotoTransientError("Final photo storage is temporarily unavailable.") from exc
            completed.append((source, destination, True))
        return completed
    except Exception:
        rollback_final_copies(completed)
        raise


def rollback_final_copies(completed: Iterable[tuple[Path, Path, bool]]) -> None:
    """Remove only final files created by the failed commit; pending originals remain intact."""
    failures = []
    for _source, destination, created in reversed(list(completed)):
        if not created:
            continue
        try:
            destination.unlink(missing_ok=True)
        except OSError as exc:
            failures.append(str(exc))
    if failures:
        raise PhotoTransientError("Final photo copies could not be completely rolled back.")



def _remove_uncommitted_final_copies(data_root: Path, manifest: dict) -> int:
    """Remove final-path copies left by an interrupted, never-committed transaction.

    A file is removed only when its content hash still matches the pending manifest. This avoids
    deleting any unrelated/replaced evidence file.
    """
    removed = 0
    photos = manifest.get("photos", {}) if isinstance(manifest, dict) else {}
    for photo_id, item in photos.items():
        try:
            destination = _final_image_path(
                data_root,
                str(manifest.get("check_id", "")),
                str(manifest.get("site_id", "")),
                str(manifest.get("bag_id", "")),
                str(manifest.get("trap_id", "")),
                str(photo_id),
            )
            expected_hash = str(item.get("sha256", ""))
            if not destination.exists() or not expected_hash:
                continue
            if hashlib.sha256(destination.read_bytes()).hexdigest() == expected_hash:
                destination.unlink(missing_ok=True)
                removed += 1
        except Exception as exc:
            _log(
                data_root, "stale_final_photo_cleanup_failed",
                check_id=str(manifest.get("check_id", "")), photo_id=str(photo_id), detail=str(exc)[:500],
            )
    return removed

def delete_transaction(data_root: Path, check_id: str) -> None:
    directory = transaction_dir(data_root, check_id)
    if directory.exists():
        shutil.rmtree(directory)
    _log(data_root, "transaction_cleared", check_id=check_id)


def cleanup_stale_transactions(data_root: Path, completed_check_ids: Iterable[str], ttl_hours: int = DEFAULT_TTL_HOURS) -> dict:
    root = pending_root(data_root)
    if not root.exists():
        return {"removed": 0, "kept": 0, "errors": 0}
    completed = set(str(x) for x in completed_check_ids)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=int(ttl_hours))
    removed = kept = errors = 0
    for directory in [p for p in root.iterdir() if p.is_dir()]:
        manifest_file = directory / "manifest.json"
        try:
            if manifest_file.exists():
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                check_id = str(manifest.get("check_id", directory.name))
                updated = str(manifest.get("updated_at", "")).rstrip("Z")
                updated_at = datetime.fromisoformat(updated).replace(tzinfo=timezone.utc) if updated else datetime.fromtimestamp(manifest_file.stat().st_mtime, tz=timezone.utc)
            else:
                check_id = directory.name
                updated_at = datetime.fromtimestamp(directory.stat().st_mtime, tz=timezone.utc)
            if check_id in completed or updated_at < cutoff:
                final_copies_removed = 0
                # Completed checks own their final evidence. Only an expired, uncommitted
                # transaction may have orphaned final-path copies from an interrupted save.
                if check_id not in completed and manifest_file.exists():
                    final_copies_removed = _remove_uncommitted_final_copies(data_root, manifest)
                shutil.rmtree(directory)
                removed += 1
                _log(
                    data_root, "stale_transaction_removed", check_id=check_id,
                    completed=check_id in completed, final_copies_removed=final_copies_removed,
                )
            else:
                kept += 1
        except Exception as exc:
            errors += 1
            _log(data_root, "stale_transaction_cleanup_failed", check_id=directory.name, detail=str(exc)[:500])
    return {"removed": removed, "kept": kept, "errors": errors}


def log_photo_event(data_root: Path, event: str, **fields) -> None:
    _log(data_root, event, **fields)
