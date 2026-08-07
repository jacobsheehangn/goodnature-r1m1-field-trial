"""Additional photo_integrity coverage added during the 7 Aug 2026 engineering
review, for invariants listed in HANDOVER_TO_CLAUDE.md section 14 that
weren't yet covered by test_photo_store.py. Runs standalone (no pytest
required) via the __main__ block, and also under `pytest -q tests/`.
"""
from __future__ import annotations

import json
from pathlib import Path

from test_photo_store import context, jpeg_payload

from photo_integrity import add_expected_photos, load_manifest, save_manifest, store_photo, verify_pending

MAX_BYTES = 2 * 1024 * 1024


def test_file_missing_blocks_save(tmp_path: Path) -> None:
    ctx = context()
    photo_id = "PHOTO-AAAABBBB"
    add_expected_photos(tmp_path, ctx, [{"photo_id": photo_id, "name": "one.jpg"}])
    store_photo(tmp_path, ctx, jpeg_payload(photo_id, "one.jpg"), MAX_BYTES)
    pending_files = list((tmp_path / ".pending_photos").rglob("*.jpg"))
    assert len(pending_files) == 1
    pending_files[0].unlink()
    gate = verify_pending(tmp_path, ctx, MAX_BYTES)
    assert gate["ready"] is False
    assert gate["file_count"] == 0


def test_hash_mismatch_blocks_save(tmp_path: Path) -> None:
    ctx = context()
    photo_id = "PHOTO-AAAABBBB"
    add_expected_photos(tmp_path, ctx, [{"photo_id": photo_id, "name": "one.jpg"}])
    store_photo(tmp_path, ctx, jpeg_payload(photo_id, "one.jpg"), MAX_BYTES)
    pending_files = list((tmp_path / ".pending_photos").rglob("*.jpg"))
    pending_files[0].write_bytes(pending_files[0].read_bytes() + b"\x00\x00")
    gate = verify_pending(tmp_path, ctx, MAX_BYTES)
    assert gate["ready"] is False
    assert any("invalid" in e for e in gate["errors"])


def test_invalid_photo_id_rejected(tmp_path: Path) -> None:
    ctx = context()
    raised = False
    try:
        add_expected_photos(tmp_path, ctx, [{"photo_id": "not-a-valid-id", "name": "one.jpg"}])
    except Exception:
        raised = True
    assert raised, "Malformed photo IDs must be rejected, not silently accepted"


def test_duplicate_expected_ids_deduped(tmp_path: Path) -> None:
    ctx = context()
    photo_id = "PHOTO-AAAABBBB"
    add_expected_photos(
        tmp_path, ctx, [{"photo_id": photo_id, "name": "a.jpg"}, {"photo_id": photo_id, "name": "a.jpg"}]
    )
    manifest = load_manifest(tmp_path, ctx["check_id"])
    assert manifest["expected_photo_ids"].count(photo_id) == 1


def test_extra_unexpected_row_flagged(tmp_path: Path) -> None:
    ctx = context()
    photo_id = "PHOTO-AAAABBBB"
    add_expected_photos(tmp_path, ctx, [{"photo_id": photo_id, "name": "one.jpg"}])
    store_photo(tmp_path, ctx, jpeg_payload(photo_id, "one.jpg"), MAX_BYTES)
    manifest = load_manifest(tmp_path, ctx["check_id"])
    ghost_id = "PHOTO-GHOSTGHOST"
    manifest["photos"][ghost_id] = dict(manifest["photos"][photo_id])
    manifest["photos"][ghost_id]["row"] = dict(manifest["photos"][photo_id]["row"])
    manifest["photos"][ghost_id]["row"]["Photo ID"] = ghost_id
    save_manifest(tmp_path, manifest)
    gate = verify_pending(tmp_path, ctx, MAX_BYTES)
    assert gate["ready"] is False


if __name__ == "__main__":
    import shutil
    import sys
    import tempfile
    import traceback

    this_module = sys.modules[__name__]
    fns = [(n, f) for n, f in vars(this_module).items() if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in fns:
        tmp = Path(tempfile.mkdtemp(prefix="extra_"))
        try:
            fn(tmp)
            print(f"PASS  {name}")
            passed += 1
        except Exception as exc:
            print(f"FAIL  {name}: {exc}")
            traceback.print_exc()
            failed += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"--- {passed} passed, {failed} failed ---")
    sys.exit(1 if failed else 0)
