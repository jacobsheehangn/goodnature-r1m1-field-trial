"""P6-7 (owner, 14 Oct 2026): what happens to photos staged for a collected kill when the check ends up with an outcome that takes none.

Today's behaviour that stays: the photos stay staged while the check is open, so switching away and back restores them.
The rule: if the check is saved with an outcome that takes no photos, none are attached, the pending folder is deleted, and one
`staged_photos_not_attached` photo event records the check ID and the count. The pending folder is also cleared after every other
successful save (the leftover-draft bug: a check without photos saves under a fresh random Check ID, so its folder was never found)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import Page

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import check_form as cf  # noqa: E402
import check_save_matrix as m  # noqa: E402
import photo_integrity as pi  # noqa: E402
from test_check_save_golden_ui import WORKBOOK, _serve  # noqa: E402

TRAP = m.PROFILES["camera_trial"]["trap"]


# ---------------------------------------------------------------- the count
def _stage(tmp_path: Path, count: int, check_id: str = "CHK-UNIT") -> dict:
    context = {"check_id": check_id, "visit_id": "V", "trap_id": "T1", "site_id": "S", "bag_id": "S-001", "window_id": "W1"}
    for payload in m._staged_photo_payloads(count):
        pi.store_photo(tmp_path, context, payload, 2 * 1024 * 1024)
    return context


def test_staged_photo_count_counts_stored_photos_only(tmp_path):
    assert pi.staged_photo_count(tmp_path, "CHK-UNIT") == 0, "no pending folder"
    context = _stage(tmp_path, 3)
    assert pi.staged_photo_count(tmp_path, "CHK-UNIT") == 3
    pi.remove_photo(tmp_path, context, "PHOTO-GOLDEN-0001")
    assert pi.staged_photo_count(tmp_path, "CHK-UNIT") == 2, "a removed photo is not counted"
    pi.add_expected_photos(tmp_path, context, [{"photo_id": "PHOTO-GOLDEN-9999", "name": "never_uploaded.jpg"}])
    assert pi.staged_photo_count(tmp_path, "CHK-UNIT") == 2, "a photo that never finished uploading is not counted"


# ---------------------------------------------------------------- the commit, on the real chain
def _chain(tmp_path: Path, case: str) -> dict:
    script = f"""
        import json, app, check_save_matrix as m
        from pathlib import Path
        with m.Pinned(app) as pin:
            out = m.run_photo_chain(app, pin, {case!r}, "extracted")
        log = Path(app.DATA_ROOT) / "photo_upload_log.jsonl"
        events = [json.loads(l) for l in log.read_text().splitlines() if l.strip()] if log.exists() else []
        print(json.dumps({{"out": out, "events": [e for e in events if e["event"] == "staged_photos_not_attached"]}}))
    """
    data_dir = tmp_path / "chain"
    data_dir.mkdir(exist_ok=True)
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir),
               PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "tests")]))
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"stdout={result.stdout[-1500:]}\nstderr={result.stderr[-3000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("case", ["staged_2_then_no_carcass", "staged_2_then_trap_fired"])
def test_saving_with_an_outcome_that_takes_no_photos_drops_them_and_logs_it(case, tmp_path):
    result = _chain(tmp_path, case)
    out = result["out"]
    assert len(out["photos"]) == 0 and out["final_files"] == [], "no photo is attached"
    assert out["pending_files_after"] == [], "the pending folder, with the two staged photos, is deleted"
    assert len(out["checks_new"]) == 1, "the check itself is saved"
    assert len(result["events"]) == 1
    event = result["events"][0]
    assert event["count"] == 2 and event["check_id"] == out["ids"][0] and event["trap_id"] == TRAP
    assert event["pending_id"] == pi.deterministic_check_id(m.VISIT_ID, TRAP)


@pytest.mark.parametrize("case", ["collected_1_photo", "collected_3_photos", "collected_0_photos"])
def test_a_check_that_takes_its_photos_logs_nothing_and_leaves_nothing(case, tmp_path):
    result = _chain(tmp_path, case)
    assert result["events"] == [] and result["out"]["pending_files_after"] == []


def test_a_check_without_photos_clears_its_draft(tmp_path):
    """The leftover-draft bug: the draft file sat in the pending folder until the 72-hour sweep."""
    script = """
        import json, app, check_save_matrix as m, photo_integrity as pi
        from pathlib import Path
        with m.Pinned(app) as pin:
            pin.reset(0)
            app.save_data(m.build_fixture(app))
            base = app.load_data()
            root = Path(app.DATA_ROOT)
            pending = pi.deterministic_check_id(m.VISIT_ID, "R1-MAN-001")
            pi.save_draft_answers(root, pending, {"finding": "Trap still set, no animal", "notes": "half done"})
            before = sorted(str(p.relative_to(root)) for p in (root / ".pending_photos").rglob("*") if p.is_file())
            cell = m._cell("camera_trial", "Trap still set, no animal", "", "Yes", "", "Yes", "", "", False, "", ("", "", "", 0))
            pin.reset()
            staged, ids = m.build_extracted(app, base, cell)
            gate = {"ready": True, "expected_count": 0, "file_count": 0, "row_count": 0, "photos": []}
            app.commit_staged_records_with_photos(
                data={n: f.copy(deep=True) for n, f in base.items()}, staged=staged, original_data={n: f.copy(deep=True) for n, f in base.items()},
                photo_gate=gate, expected_photo_count=0, record_id=ids[0], photos_id_column="Check ID", verify_persisted=lambda r: {},
                log_prefix="check", log_fields={}, record_noun="check", record_description="check", pending_check_id=pending)
            after = sorted(str(p.relative_to(root)) for p in (root / ".pending_photos").rglob("*") if p.is_file()) if (root / ".pending_photos").exists() else []
        print(json.dumps({"before": before, "after": after}))
    """
    data_dir = tmp_path / "draft"
    data_dir.mkdir()
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir),
               PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "tests")]))
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"stdout={result.stdout[-1500:]}\nstderr={result.stderr[-3000:]}"
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert len(out["before"]) == 1 and out["before"][0].endswith("draft_answers.json")
    assert out["after"] == [], "the draft folder is cleared by its own ID after the save"


# ---------------------------------------------------------------- the real page
def _sheet(data_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_excel(data_dir / WORKBOOK, sheet_name=name, dtype=str).fillna("")


def _kill_with_two_photos(page: Page, url: str, tmp_path: Path) -> None:
    cf.start_visit_and_open(page, url, TRAP)
    cf.pick_finding(page, "Dead animal found")
    cf.pick(page, "carcass", "Yes")
    cf.stage_photos(page, tmp_path, 2)


SWITCHES = {
    "another finding": lambda page: cf.pick_finding(page, "Trap fired, no animal"),
    "carcass No": lambda page: cf.pick(page, "carcass", "No"),
}
SWITCH_BACK = {
    "another finding": lambda page: cf.pick_finding(page, "Dead animal found"),
    "carcass No": lambda page: cf.pick(page, "carcass", "Yes"),
}


@pytest.mark.parametrize("how", list(SWITCHES))
def test_switching_away_and_back_keeps_the_staged_photos(how, tmp_path, page: Page):
    page.set_viewport_size({"width": 414, "height": 896})
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _serve(data_dir) as url:
        _kill_with_two_photos(page, url, tmp_path)
        staged = cf.pending_files(data_dir)
        assert len([f for f in staged if f.endswith(".jpg")]) == 2
        SWITCHES[how](page)
        assert cf.pending_files(data_dir) == staged, "nothing is deleted while the check is open"
        SWITCH_BACK[how](page)
        page.wait_for_timeout(2500)
        assert "2 photos saved" in cf.uploader_text(page) or cf.body_lines(page, "2 photos saved")
        assert cf.pending_files(data_dir) == staged


@pytest.mark.parametrize("how", list(SWITCHES))
def test_saving_after_switching_away_drops_the_photos_and_logs_it(how, tmp_path, page: Page):
    page.set_viewport_size({"width": 414, "height": 896})
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _serve(data_dir) as url:
        _kill_with_two_photos(page, url, tmp_path)
        SWITCHES[how](page)
        if how == "another finding":
            cf.pick(page, "service", "Yes")
            cf.pick(page, "camera", "Yes")
        else:
            cf.pick_species(page, "Rat", "Norway rat")
            cf.pick(page, "service", "Yes")
            cf.pick(page, "camera", "Yes")
        cf.save_check(page)
        checks = _sheet(data_dir, "Checks")
        assert len(checks) == 1 and len(_sheet(data_dir, "Photos")) == 0, "the check is saved, no photo is attached"
        assert cf.pending_files(data_dir) == [], "the staged photos are deleted at Save, and nothing is left behind"
        events = cf.photo_events(data_dir, "staged_photos_not_attached")
        assert len(events) == 1 and events[0]["count"] == 2 and events[0]["check_id"] == checks.iloc[0]["Check ID"]


def test_a_check_without_photos_leaves_no_draft_folder_behind(tmp_path, page: Page):
    page.set_viewport_size({"width": 414, "height": 896})
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _serve(data_dir) as url:
        cf.start_visit_and_open(page, url, TRAP)
        cf.pick_finding(page, "Trap still set, no animal")
        cf.pick(page, "service", "Yes")
        cf.pick(page, "camera", "Yes")
        assert cf.pending_files(data_dir), "the half-answered form is saved as a draft"
        cf.save_check(page)
        assert len(_sheet(data_dir, "Checks")) == 1
        assert cf.pending_files(data_dir) == [], "once the check is saved its draft is gone"
        assert cf.photo_events(data_dir, "staged_photos_not_attached") == []


def test_a_kill_saved_with_its_photos_attaches_them_and_logs_nothing(tmp_path, page: Page):
    page.set_viewport_size({"width": 414, "height": 896})
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with _serve(data_dir) as url:
        _kill_with_two_photos(page, url, tmp_path)
        cf.pick_species(page, "Rat", "Norway rat")
        cf.pick_condition(page, "Dead and apparently normal")
        cf.tick(page, __import__("re").compile(r"Bag labelled"))
        cf.pick(page, "service", "Yes")
        cf.pick(page, "camera", "Yes")
        cf.save_check(page)
        assert len(_sheet(data_dir, "Photos")) == 2
        assert cf.pending_files(data_dir) == []
        assert cf.photo_events(data_dir, "staged_photos_not_attached") == []
