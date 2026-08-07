from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image

from photo_integrity import (
    add_expected_photos,
    apply_final_copies,
    build_finalisation_plan,
    cleanup_stale_transactions,
    deterministic_check_id,
    load_manifest,
    record_failure,
    remove_photo,
    rollback_final_copies,
    store_photo,
    verify_pending,
)

MAX_BYTES = 2 * 1024 * 1024


def jpeg_payload(photo_id: str, name: str, size=(900, 1200), colour=(80, 120, 160)) -> dict:
    image = Image.new("RGB", size, colour)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=82)
    raw = buffer.getvalue()
    return {
        "photo_id": photo_id,
        "name": name,
        "original_size": len(raw),
        "prepared_size": len(raw),
        "width": size[0],
        "height": size[1],
        "mime": "image/jpeg",
        "data_url": "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii"),
        "captured_time": "2026-08-07T12:00:00Z",
        "attempt": 1,
    }


def context() -> dict:
    visit = "VIS-MOA-20260807-ABC1"
    trap = "M15-8"
    return {
        "check_id": deterministic_check_id(visit, trap),
        "visit_id": visit,
        "trap_id": trap,
        "site_id": "MOA",
        "bag_id": "MOA-002",
        "window_id": "WIN-M15-8-001",
    }


def test_durable_expected_file_and_row_counts(tmp_path: Path) -> None:
    ctx = context()
    ids = ["PHOTO-AAAABBBB", "PHOTO-CCCCDDDD", "PHOTO-EEEEFFFF"]
    add_expected_photos(tmp_path, ctx, [{"photo_id": x, "name": f"{i}.jpg"} for i, x in enumerate(ids)])

    first = jpeg_payload(ids[0], "one.jpg")
    store_photo(tmp_path, ctx, first, MAX_BYTES)
    gate = verify_pending(tmp_path, ctx, MAX_BYTES)
    assert gate["expected_count"] == 3
    assert gate["file_count"] == 1
    assert gate["row_count"] == 1
    assert gate["ready"] is False

    # Same Photo ID and same bytes are idempotent.
    store_photo(tmp_path, ctx, first, MAX_BYTES)
    manifest = load_manifest(tmp_path, ctx["check_id"])
    assert len(manifest["photos"]) == 1

    store_photo(tmp_path, ctx, jpeg_payload(ids[1], "two.jpg", colour=(100, 140, 180)), MAX_BYTES)
    store_photo(tmp_path, ctx, jpeg_payload(ids[2], "three.jpg", colour=(120, 160, 200)), MAX_BYTES)
    gate = verify_pending(tmp_path, ctx, MAX_BYTES)
    assert gate["expected_count"] == gate["file_count"] == gate["row_count"] == 3
    assert gate["ready"] is True


def test_remove_tombstone_blocks_late_upload(tmp_path: Path) -> None:
    ctx = context()
    photo_id = "PHOTO-AAAABBBB"
    add_expected_photos(tmp_path, ctx, [{"photo_id": photo_id, "name": "one.jpg"}])
    payload = jpeg_payload(photo_id, "one.jpg")
    store_photo(tmp_path, ctx, payload, MAX_BYTES)
    remove_photo(tmp_path, ctx, photo_id)

    result = store_photo(tmp_path, ctx, payload, MAX_BYTES)
    assert result["status"] == "removed"
    gate = verify_pending(tmp_path, ctx, MAX_BYTES)
    assert gate["expected_count"] == 0
    assert gate["row_count"] == 0
    assert gate["ready"] is True
    assert photo_id in gate["removed_ids"]


def test_finalise_and_rollback_copies_keep_pending_recovery_files(tmp_path: Path) -> None:
    ctx = context()
    ids = ["PHOTO-AAAABBBB", "PHOTO-CCCCDDDD"]
    add_expected_photos(tmp_path, ctx, [{"photo_id": x, "name": f"{x}.jpg"} for x in ids])
    for i, photo_id in enumerate(ids):
        store_photo(tmp_path, ctx, jpeg_payload(photo_id, f"{i}.jpg", colour=(80 + i * 20, 120, 160)), MAX_BYTES)

    plan = build_finalisation_plan(tmp_path, ctx, MAX_BYTES)
    assert len(plan["rows"]) == 2
    completed = apply_final_copies(plan)
    assert all(destination.exists() for _, destination, _ in completed)
    assert all(source.exists() for source, _, _ in completed)  # pending originals survive until workbook commit
    assert all("evidence/" in row["File Path"] for row in plan["rows"])
    rollback_final_copies(completed)
    assert all(source.exists() for source, _, _ in completed)
    assert all(not destination.exists() for _, destination, created in completed if created)


def test_manual_failure_state_is_durable(tmp_path: Path) -> None:
    ctx = context()
    photo_id = "PHOTO-AAAABBBB"
    add_expected_photos(tmp_path, ctx, [{"photo_id": photo_id, "name": "one.jpg"}])
    record_failure(
        tmp_path, ctx, photo_id,
        retryable=True,
        error_code="automatic_retries_exhausted",
        user_error="Upload failed",
        manual_required=True,
        attempt=4,
    )
    gate = verify_pending(tmp_path, ctx, MAX_BYTES)
    assert gate["ready"] is False
    assert gate["manual_failure_count"] == 1
    assert gate["photos"][0]["retryable"] is True
    assert gate["photos"][0]["manual_required"] is True


def test_retry_with_same_photo_id_but_different_bytes_is_rejected(tmp_path: Path) -> None:
    from photo_integrity import PhotoPermanentError

    ctx = context()
    photo_id = "PHOTO-AAAABBBB"
    add_expected_photos(tmp_path, ctx, [{"photo_id": photo_id, "name": "one.jpg"}])
    store_photo(tmp_path, ctx, jpeg_payload(photo_id, "one.jpg", colour=(80, 120, 160)), MAX_BYTES)
    try:
        store_photo(tmp_path, ctx, jpeg_payload(photo_id, "one.jpg", colour=(200, 80, 100)), MAX_BYTES)
    except PhotoPermanentError:
        pass
    else:
        raise AssertionError("Different bytes must not replace an existing Photo ID.")


def test_interrupted_final_copy_can_be_reused_on_retry(tmp_path: Path) -> None:
    ctx = context()
    photo_id = "PHOTO-AAAABBBB"
    add_expected_photos(tmp_path, ctx, [{"photo_id": photo_id, "name": "one.jpg"}])
    store_photo(tmp_path, ctx, jpeg_payload(photo_id, "one.jpg"), MAX_BYTES)
    first_plan = build_finalisation_plan(tmp_path, ctx, MAX_BYTES)
    first_copy = apply_final_copies(first_plan)
    assert first_copy[0][2] is True
    assert first_copy[0][0].exists() and first_copy[0][1].exists()

    # Simulate a process interruption after final copy but before workbook commit. A second
    # finalisation must recognise the identical destination and not duplicate/replace it.
    retry_plan = build_finalisation_plan(tmp_path, ctx, MAX_BYTES)
    retry_copy = apply_final_copies(retry_plan)
    assert retry_copy[0][2] is False
    assert retry_copy[0][0].exists() and retry_copy[0][1].exists()


def test_stale_cleanup_removes_matching_orphan_final_copy(tmp_path: Path) -> None:
    ctx = context()
    photo_id = "PHOTO-AAAABBBB"
    add_expected_photos(tmp_path, ctx, [{"photo_id": photo_id, "name": "one.jpg"}])
    store_photo(tmp_path, ctx, jpeg_payload(photo_id, "one.jpg"), MAX_BYTES)
    plan = build_finalisation_plan(tmp_path, ctx, MAX_BYTES)
    completed = apply_final_copies(plan)
    final_path = completed[0][1]
    assert final_path.exists()

    manifest_file = tmp_path / ".pending_photos" / ctx["check_id"] / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["updated_at"] = (datetime.utcnow() - timedelta(hours=80)).replace(microsecond=0).isoformat() + "Z"
    manifest_file.write_text(json.dumps(manifest))

    result = cleanup_stale_transactions(tmp_path, completed_check_ids=[], ttl_hours=72)
    assert result["removed"] == 1
    assert not final_path.exists()


def test_cleanup_removes_only_stale_uncommitted_transaction(tmp_path: Path) -> None:
    ctx = context()
    photo_id = "PHOTO-AAAABBBB"
    add_expected_photos(tmp_path, ctx, [{"photo_id": photo_id, "name": "one.jpg"}])
    store_photo(tmp_path, ctx, jpeg_payload(photo_id, "one.jpg"), MAX_BYTES)
    manifest_path = tmp_path / ".pending_photos" / ctx["check_id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["updated_at"] = (datetime.utcnow() - timedelta(hours=80)).replace(microsecond=0).isoformat() + "Z"
    manifest_path.write_text(json.dumps(manifest))

    result = cleanup_stale_transactions(tmp_path, completed_check_ids=[], ttl_hours=72)
    assert result["removed"] == 1
    assert not manifest_path.exists()
