"""Pinned pre-migration backup (Deploy A). The automatic backups rotate (one per save, the newest 20 kept), so the workbook as it was before a
new version first wrote to it is gone within hours. A pin is a byte-for-byte copy of the live file taken immediately before the first save that
changes the workbook's layout (its sheets and columns): never overwritten, keyed by the layout being written (so a later version that adds
columns gets its own pin), outside the rotation, listed by the in-app restore, and unable to block a save.

Everything runs in a subprocess against a temporary data folder (app.py routes pages at import, so tests never import it here)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from test_trial_model_ui import _serve  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# A workbook as the live app has it today: no Trials sheet and no Trial ID columns. old_layout() leaves one on disk and returns its sha256.
PREAMBLE = """
import hashlib, json, logging, os, sys
logging.disable(logging.CRITICAL)
sys.path.insert(0, os.getcwd())
import pandas as pd
import app

def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

def current_layout():
    # A fresh folder starts from the bundled workbook, which is an older layout, so this first save pins it: forget that pin.
    app.st.session_state.pop(app.DATA_LOADED_MTIME_KEY, None)
    app.save_data(app.create_sample_data())
    for pin in app.BACKUP_DIR.glob("pinned_*"):
        pin.unlink()

def old_layout():
    current_layout()
    return strip_to_old_layout()

def strip_to_old_layout():
    sheets = pd.read_excel(app.DATA_FILE, sheet_name=None, dtype=str)
    sheets.pop("Trials", None)
    for name in ("Windows", "Kills"):
        if name in sheets:
            sheets[name] = sheets[name].drop(columns=["Trial ID"], errors="ignore")
    with pd.ExcelWriter(app.DATA_FILE, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return sha(app.DATA_FILE)

def bump(i):
    # The file was just replaced behind the app's back (a restore, or the old layout written by hand), which the app's stale-save guard would
    # rightly refuse; a new session has no tracked modification time, so this behaves like one.
    app.st.session_state.pop(app.DATA_LOADED_MTIME_KEY, None)
    data = {k: v.copy() for k, v in app.load_data().items()}
    cols = app.SHEETS["Audit Log"]
    data["Audit Log"] = pd.concat([data["Audit Log"], pd.DataFrame([{**{c: "" for c in cols}, cols[0]: f"TEST-{i}"}])], ignore_index=True)
    app.save_data(data)

def pins():
    return sorted(p.name for p in app.BACKUP_DIR.glob("pinned_*.xlsx"))

def rotating():
    return sorted(app.BACKUP_DIR.glob(app.DATA_FILE.stem + "_*.xlsx"))

def finish(out):
    print("RESULT" + json.dumps(out))
"""


def _run(tmp_path: Path, body: str) -> dict:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir), STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(PREAMBLE) + textwrap.dedent(body)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, f"stdout={result.stdout[-1500:]}\nstderr={result.stderr[-3000:]}"
    line = [ln for ln in result.stdout.splitlines() if ln.startswith("RESULT")][-1]
    return json.loads(line[len("RESULT"):])


def test_the_first_save_that_changes_the_layout_pins_a_byte_identical_copy_of_the_live_file(tmp_path: Path) -> None:
    out = _run(tmp_path, """
        original = old_layout()
        assert "Trials" not in pd.ExcelFile(app.DATA_FILE).sheet_names
        bump(1)
        names = pins()
        pin = app.BACKUP_DIR / names[0]
        note = json.loads(pin.with_suffix(".json").read_text())
        finish({"pins": names, "original": original, "pin_sha": sha(pin), "live_has_trials": "Trials" in pd.ExcelFile(app.DATA_FILE).sheet_names,
                "pin_has_trials": "Trials" in pd.ExcelFile(pin).sheet_names, "live_is_current_layout": app.workbook_layout_of(app.DATA_FILE) == app.schema_layout(), "note": note})
    """)
    assert len(out["pins"]) == 1 and out["pins"][0].startswith("pinned_field_trial_data_v8_6_5_before_layout_"), out["pins"]
    assert out["pin_sha"] == out["original"], "the pin is the live file byte for byte, as it was before the save"
    assert out["live_has_trials"] and out["live_is_current_layout"] and not out["pin_has_trials"]
    assert out["note"]["sha256"] == out["original"] and "adds sheet Trials" in out["note"]["change"] and "Windows.Trial ID" in out["note"]["change"], out["note"]


def test_a_pin_is_never_overwritten_once_it_exists(tmp_path: Path) -> None:
    out = _run(tmp_path, """
        first = old_layout()
        bump(1)
        pin = app.BACKUP_DIR / pins()[0]
        # the same layout change happens again (a rollback to the old code, then a redeploy): a different old file, the same layout being written
        second = strip_to_old_layout()
        bump(2)
        finish({"first": first, "second": second, "pins": pins(), "pin_sha": sha(pin)})
    """)
    assert out["first"] != out["second"] and len(out["pins"]) == 1
    assert out["pin_sha"] == out["first"], "the first pin stands: it was not replaced by the newer old file"


def test_the_pin_survives_25_saves_while_the_rotation_drops_the_oldest_backups(tmp_path: Path) -> None:
    out = _run(tmp_path, """
        original = old_layout()
        bump(0)
        pin = app.BACKUP_DIR / pins()[0]
        for i in range(1, 26):
            bump(i)
        finish({"original": original, "pins": pins(), "pin_sha": sha(pin), "rotating": len(rotating()),
                "an_automatic_backup_still_has_the_original_bytes": any(sha(p) == original for p in rotating())})
    """)
    assert out["rotating"] == 20, "the rotation is still keeping only the newest 20"
    assert not out["an_automatic_backup_still_has_the_original_bytes"], "so the automatic backup of the old file has rotated out"
    assert len(out["pins"]) == 1 and out["pin_sha"] == out["original"], "while the pin is still there, unchanged"


def test_restoring_the_pin_after_25_saves_gives_back_the_original_file_byte_for_byte(tmp_path: Path) -> None:
    out = _run(tmp_path, """
        original = old_layout()
        for i in range(26):
            bump(i)
        listed = app.available_backups()
        pin = listed[0]
        safety = app.restore_backup(pin)
        restored_sha = sha(app.DATA_FILE)
        data = app.load_data()            # the current code reads the restored old-layout file
        bump(99)                          # and its first save makes the same layout change again
        finish({"original": original, "restored": restored_sha, "first_listed": pin.name, "label": app.backup_label(pin), "safety_copy_made": safety.exists(),
                "trials_blank": len(data["Trials"]) == 0, "pins": pins(), "pin_sha_after": sha(pin)})
    """)
    assert out["restored"] == out["original"], "restoring the pin puts the live file back byte-identical"
    assert out["first_listed"].startswith("pinned_") and out["label"].startswith("PINNED, never rotated out"), (out["first_listed"], out["label"])
    assert out["safety_copy_made"] and out["trials_blank"]
    assert len(out["pins"]) == 1 and out["pin_sha_after"] == out["original"], "the next layout-changing save did not make or replace a pin"


def test_a_failed_pin_copy_never_blocks_the_save(tmp_path: Path) -> None:
    out = _run(tmp_path, """
        import shutil
        original = old_layout()
        real_copyfile = shutil.copyfile
        def failing(src, dst, *a, **k):          # every copy to a pin's temp name fails, after writing part of it
            if os.path.basename(str(dst)).startswith(".pin_"):
                open(dst, "wb").write(b"partial")
                raise OSError(28, "No space left on device (injected)")
            return real_copyfile(src, dst, *a, **k)
        shutil.copyfile = failing
        bump(1)                                  # must not raise
        live = pd.ExcelFile(app.DATA_FILE)
        rows = pd.read_excel(app.DATA_FILE, sheet_name="Audit Log", dtype=str)
        finish({"saved": "Trials" in live.sheet_names and "TEST-1" in rows.iloc[:, 0].tolist(), "pins": pins(), "leftover_temp": [p.name for p in app.BACKUP_DIR.glob(".pin_*")],
                "automatic_backup_has_the_original": any(sha(p) == original for p in rotating())})
    """)
    assert out["saved"], "the save went through"
    assert out["pins"] == [] and out["leftover_temp"] == [], "no pin, and no half-written file left behind"
    assert out["automatic_backup_has_the_original"], "the ordinary automatic backup of the old file is still taken"


def test_a_pin_that_fails_once_is_made_from_the_automatic_backup_in_the_same_save(tmp_path: Path) -> None:
    out = _run(tmp_path, """
        import shutil
        original = old_layout()
        real_copyfile = shutil.copyfile
        calls = {"pin": 0}
        def flaky(src, dst, *a, **k):            # the first attempt (from the live file) fails, the second (from the automatic backup) works
            if os.path.basename(str(dst)).startswith(".pin_"):
                calls["pin"] += 1
                if calls["pin"] == 1:
                    raise OSError(5, "Input/output error (injected)")
            return real_copyfile(src, dst, *a, **k)
        shutil.copyfile = flaky
        bump(1)
        names = pins()
        finish({"attempts": calls["pin"], "pins": names, "pin_sha": sha(app.BACKUP_DIR / names[0]) if names else None, "original": original})
    """)
    assert out["attempts"] == 2 and len(out["pins"]) == 1
    assert out["pin_sha"] == out["original"], "the second chance holds the same bytes as the live file had"


def test_each_layout_gets_its_own_pin_so_a_later_versions_new_columns_are_pinned_too(tmp_path: Path) -> None:
    out = _run(tmp_path, """
        original = old_layout()
        bump(1)
        first_pin = app.BACKUP_DIR / pins()[0]
        first_sha = sha(first_pin)
        # a later version adds a column to Windows (Deploy B adds the necropsy columns)
        app.SHEETS["Windows"] = list(app.SHEETS["Windows"]) + ["Necropsy Extra (test)"]
        before_second_save = sha(app.DATA_FILE)
        bump(2)
        names = pins()
        second_pin = [app.BACKUP_DIR / n for n in names if app.BACKUP_DIR / n != first_pin][0]
        note = json.loads(second_pin.with_suffix(".json").read_text())
        bump(3)
        finish({"original": original, "first_sha": first_sha, "first_after": sha(first_pin), "before_second_save": before_second_save, "second_sha": sha(second_pin),
                "second_has_extra": "Necropsy Extra (test)" in pd.read_excel(second_pin, sheet_name="Windows").columns, "pins_after_third_save": len(pins()), "note": note})
    """)
    assert out["first_sha"] == out["original"] == out["first_after"], "the first pin is untouched"
    assert out["second_sha"] == out["before_second_save"], "the second pin is the file as the first version left it"
    assert not out["second_has_extra"] and "adds column Windows.Necropsy Extra (test)" in out["note"]["change"], out["note"]
    assert out["pins_after_third_save"] == 2, "an ordinary save in the same layout makes no third pin"


def test_ordinary_saves_make_no_pin_and_a_file_already_in_the_current_layout_gets_none(tmp_path: Path) -> None:
    out = _run(tmp_path, """
        current_layout()
        for i in range(4):
            bump(i)
        finish({"pins": pins(), "json": [p.name for p in app.BACKUP_DIR.glob("pinned_*")], "available_all_rotating": all(not p.name.startswith("pinned_") for p in app.available_backups())})
    """)
    assert out["pins"] == [] and out["json"] == [] and out["available_all_rotating"]


def test_the_in_app_restore_lists_the_pin_first_with_what_it_was_kept_for(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    seed = PREAMBLE + """
old_layout()
bump(1)
bump(2)
"""
    page.set_viewport_size({"width": 1280, "height": 900})
    with _serve(data_dir, seed, extra_env={"R1M1_ENABLE_RECOVERY_TOOLS": "1"}) as url:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        expect(page.get_by_role("heading", name="Trap sites", exact=True)).to_be_visible(timeout=40_000)
        page.get_by_role("button", name="Administration", exact=False).click()
        page.get_by_role("link", name="Data & records", exact=True).click()
        expect(page.get_by_text("Data & records", exact=True).last).to_be_visible(timeout=30_000)
        page.get_by_text("Export and backup", exact=True).click()
        page.get_by_text("Emergency recovery tools", exact=True).click()
        # The selected entry of the Backup list is the first one, and the first is the pin, named for what it was kept for.
        backup = page.get_by_role("combobox", name="Backup")
        expect(backup).to_have_value(re.compile(r"^PINNED, never rotated out: the workbook just before the first save that adds sheet Trials"), timeout=20_000)
        assert "pinned_field_trial_data_v8_6_5_before_layout_" in backup.input_value()
