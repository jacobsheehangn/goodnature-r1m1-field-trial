"""Phase 5 (TRIAL_LIFECYCLE_BRIEF.md, A2) UI tests, driving the real app:

1. The check form: under "Dead animal found", "Carcass collected?" -
   "No" saves with no Bag ID, bag tick, photos or necropsy task and still
   counts as a kill; "Yes" is the original form and still issues the next bag.
2. The one-time correction for existing records, and the Data & records
   correction form still showing the new value (not silently the first option).
3. Trial Performance on a controlled dataset (the brief's 17 / 14 / 12 style
   arithmetic): the awaiting callout, the "counted but not assessed" line,
   the extended footer sentence, and the Evidence card's Unresolved line."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = "field_trial_data_v8_6_5.xlsx"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start(tmp_path: Path, seed: str = ""):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "R1M1_ENVIRONMENT": "local",
            "R1M1_ALLOW_NO_AUTH": "true",
            "R1M1_SEED_MODE": "clean",
            "R1M1_DATA_DIR": str(data_dir),
        }
    )
    if seed:
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(seed)],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr[-2000:]}"
    port = _free_port()
    env2 = env.copy()
    env2["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.address", "127.0.0.1", "--server.port", str(port),
            "--server.headless", "true", "--browser.gatherUsageStats", "false",
        ],
        cwd=ROOT, env=env2, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Local Streamlit process exited before becoming ready.")
        try:
            with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2) as response:
                if response.status == 200:
                    return process, url, data_dir
        except Exception:
            time.sleep(0.25)
    process.kill()
    raise RuntimeError("Local Streamlit app did not become ready within 60 seconds.")


def _stop(process) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture
def clean_app(tmp_path: Path):
    process, url, data_dir = _start(tmp_path)
    try:
        yield url, data_dir
    finally:
        _stop(process)


KILL_SEED = """
    import json, app, pandas as pd
    data = app.create_sample_data()
    traps = data["Traps"][data["Traps"]["Product"] == "R1"].iloc[:2]
    for i, trap in enumerate(traps.itertuples()):
        wid = f"TEST-NC-W{i}"
        wrow = {c: "" for c in app.SHEETS["Windows"]}
        wrow.update({
            "Window ID": wid, "Trap ID": trap._1, "Product": trap.Product, "Build Version": trap._3, "Site ID": trap._4,
            "Status": "Closed", "Start Time": "2026-08-01 00:00:00", "End Time": "2026-08-02 00:00:00",
            "Finding At Close": "Dead animal found", "Bag ID": f"BAG-{i}", "Camera Assigned": "No", "Species": "Rat",
            "Final Humane Kill": "Pending", "Necropsy Status": "Not started", "Review Status": "Open",
        })
        data["Windows"] = pd.concat([data["Windows"], pd.DataFrame([wrow])], ignore_index=True)
        crow = {c: "" for c in app.SHEETS["Checks"]}
        crow.update({"Check ID": f"TEST-NC-C{i}", "Visit ID": "V", "Trap ID": trap._1, "Window Closed": wid,
                     "Check Time": "2026-08-02 00:00:00", "Finding": "Dead animal found", "Bag ID": f"BAG-{i}",
                     "Animal Cleared": "Yes", "Animal Bagged": "Yes"})
        data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([crow])], ignore_index=True)
        frow = [f"TEST-NC-FU{i}", "Necropsy review", trap._4, trap._1, "V", wid, f"BAG-{i}", app.dtstr(), "Normal", "Dead animal collected", "d", "Open", "", ""]
        data["Followups"] = pd.concat([data["Followups"], pd.DataFrame([frow], columns=app.SHEETS["Followups"])], ignore_index=True)
    app.save_data(data)
"""


def _pick(page: Page, label: str, value: str, exact: bool = True) -> None:
    combo = page.get_by_role("combobox", name=label, exact=True)
    combo.click()
    page.keyboard.type(value)
    page.wait_for_timeout(200)
    option = page.get_by_role("option", name=value, exact=exact)
    (option if exact else option.first).click()
    page.wait_for_timeout(200)


def _radio(page: Page, group: str, option: str) -> None:
    page.get_by_role("radiogroup", name=group).get_by_role("radio", name=option, exact=True).check(force=True)


def _open_check(page: Page, url: str, nth: int) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first.click()
    expect(page.get_by_text("Select the trap you are standing at.", exact=True)).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Check", exact=True).nth(nth).click()
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)


def _finish_routine_tail(page: Page, has_camera: bool) -> None:
    _radio(page, "Trap relured, reset and ready?", "Yes")
    if has_camera:
        _radio(page, "Camera working and covering the trap?", "Yes")
    save = page.get_by_role("button", name=re.compile(r"^Save check$"))
    expect(save).to_be_enabled(timeout=10_000)
    save.click()
    expect(page.get_by_text("saved", exact=False).first).to_be_visible(timeout=30_000)


def test_no_carcass_kill_saves_without_bag_photos_or_necropsy_and_a_collected_kill_is_unchanged(
    page: Page, clean_app
) -> None:
    url, data_dir = clean_app

    # 1. A kill with NO carcass, on the first R1 trap (the one with a camera).
    _open_check(page, url, nth=1)
    page.get_by_role("radio", name="Dead animal found").check(force=True)
    expect(page.get_by_text("Carcass collected?", exact=True)).to_be_visible(timeout=15_000)
    # Nothing about a bag until the question is answered.
    assert page.get_by_text("Bag ID:", exact=False).count() == 0
    _radio(page, "Carcass collected?", "No")
    expect(page.get_by_text("No Bag ID, bag tick or necropsy task. This kill counts, but can't be assessed.", exact=True)).to_be_visible(timeout=15_000)
    assert page.get_by_text("Bag ID:", exact=False).count() == 0
    assert page.get_by_text("Photos", exact=True).count() == 0
    assert page.get_by_text("Animal condition when found", exact=True).count() == 0
    assert page.get_by_role("checkbox", name=re.compile("Bag labelled")).count() == 0
    # Species is still required, and Rat type when it is a Rat.
    _radio(page, "Species", "Rat")
    expect(page.get_by_role("radiogroup", name="Rat type")).to_be_visible(timeout=10_000)
    _radio(page, "Rat type", "Ship rat")
    _finish_routine_tail(page, has_camera=True)

    # 2. A kill WITH a carcass, on the next trap: the original form, and the
    # next bag number must still be the first one - the no-carcass kill used none.
    page.get_by_role("button", name="Check", exact=True).nth(0).click()
    expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=30_000)
    page.get_by_role("radio", name="Dead animal found").check(force=True)
    _radio(page, "Carcass collected?", "Yes")
    expect(page.get_by_text(re.compile(r"^Bag ID: [A-Z]{3}-001$"))).to_be_visible(timeout=15_000)
    expect(page.get_by_text("Photos", exact=True)).to_be_visible()
    _radio(page, "Species", "Rat")
    _radio(page, "Rat type", "Norway rat")
    _radio(page, "Animal condition when found", "Dead and apparently normal")
    page.get_by_role("checkbox", name=re.compile(r"Bag labelled")).evaluate("el => el.click()")
    _finish_routine_tail(page, has_camera=False)

    workbook = data_dir / WORKBOOK
    checks = pd.read_excel(workbook, sheet_name="Checks", dtype=str).fillna("")
    windows = pd.read_excel(workbook, sheet_name="Windows", dtype=str).fillna("")
    followups = pd.read_excel(workbook, sheet_name="Followups", dtype=str).fillna("")
    kills = checks[checks["Finding"] == "Dead animal found"]
    assert len(kills) == 2

    no_carcass_check = kills[kills["Bag ID"] == ""].iloc[0]
    assert no_carcass_check["Animal Condition When Found"] == "Unable to assess"
    assert no_carcass_check["Animal Cleared"] == "No" and no_carcass_check["Animal Bagged"] == "No"
    assert no_carcass_check["Species"] == "Rat" and no_carcass_check["Rat Type"] == "Ship rat"
    window = windows[windows["Window ID"] == no_carcass_check["Window Closed"]].iloc[0]
    assert window["Finding At Close"] == "Dead animal found", "it must still count as a kill"
    assert window["Final Humane Kill"] == "Not assessed — no carcass"
    assert window["Necropsy Status"] == "Not applicable — no carcass"
    assert window["Necropsy Assessment"] == "Not applicable — no carcass"
    assert window["Bag ID"] == ""
    tasks = followups[followups["Window ID"] == window["Window ID"]]
    assert tasks["Follow-up Type"].tolist() == ["Camera review"], "camera review as today, and no necropsy task"
    assert window["Review Status"] == "Open"

    collected_check = kills[kills["Bag ID"] != ""].iloc[0]
    assert re.fullmatch(r"[A-Z]{3}-001", collected_check["Bag ID"]), "no bag number may be consumed by the no-carcass kill"
    collected_window = windows[windows["Window ID"] == collected_check["Window Closed"]].iloc[0]
    assert collected_window["Final Humane Kill"] == "Pending"
    collected_tasks = followups[followups["Window ID"] == collected_window["Window ID"]]
    assert "Necropsy review" in collected_tasks["Follow-up Type"].tolist()


def test_one_time_correction_and_the_correction_form_still_shows_the_new_value(page: Page, tmp_path: Path) -> None:
    process, url, data_dir = _start(tmp_path, KILL_SEED)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
        page.get_by_role("button", name="Administration", exact=False).click()
        page.get_by_role("link", name="Data & records", exact=True).click()
        expect(page.get_by_text("What you are recording", exact=True)).to_be_visible(timeout=30_000)

        _pick(page, "Record type", "Kill with no carcass")
        expect(page.get_by_text("2 kills with an open necropsy review.", exact=True)).to_be_visible(timeout=15_000)
        button = page.get_by_role("button", name="Mark as no carcass collected", exact=True)
        expect(button).to_be_disabled()  # nothing changes without the owner's confirmation
        confirm = page.get_by_role("checkbox", name=re.compile("This kill had no carcass collected"))
        confirm.focus()
        page.keyboard.press("Space")
        expect(confirm).to_be_checked(timeout=10_000)
        expect(button).to_be_enabled(timeout=10_000)
        button.click()
        expect(page.get_by_text("Kill corrected.", exact=True)).to_be_visible(timeout=30_000)
        expect(page.get_by_text("1 kill with an open necropsy review.", exact=True)).to_be_visible(timeout=15_000)

        workbook = data_dir / WORKBOOK
        windows = pd.read_excel(workbook, sheet_name="Windows", dtype=str).fillna("")
        done = windows[windows["Final Humane Kill"] == "Not assessed — no carcass"]
        assert len(done) == 1 and done.iloc[0]["Bag ID"] == ""
        untouched = windows[windows["Window ID"].str.startswith("TEST-NC-W") & (windows["Final Humane Kill"] == "Pending")]
        assert len(untouched) == 1, "only the confirmed record may change"
        followups = pd.read_excel(workbook, sheet_name="Followups", dtype=str).fillna("")
        assert (followups["Status"] == "Resolved — no carcass collected").sum() == 1
        audit = pd.read_excel(workbook, sheet_name="Audit Log", dtype=str).fillna("")
        assert (audit["Record Type"] == "Kill record").sum() == 1

        # The correction form must show the new value, not fall back to the first
        # option ("Yes"), which a save would then silently write.
        corrected_id = done.iloc[0]["Window ID"]
        _pick(page, "Record type", "Necropsy evidence")
        window_picker = page.get_by_role("combobox", name="Select closed test window", exact=True)
        window_picker.click()
        page.keyboard.type(corrected_id)
        page.wait_for_timeout(200)
        page.get_by_role("option", name=re.compile(re.escape(corrected_id))).first.click()
        expect(page.get_by_role("combobox", name="Final Humane Kill", exact=True)).to_have_value(
            "Not assessed — no carcass", timeout=15_000
        )
        expect(page.get_by_role("combobox", name="Necropsy Status", exact=True)).to_have_value(
            "Not applicable — no carcass", timeout=15_000
        )
        expect(page.get_by_role("combobox", name="Necropsy Assessment", exact=True)).to_have_value(
            "Not applicable — no carcass", timeout=15_000
        )
    finally:
        _stop(process)


PERFORMANCE_SEED = """
    import app, pandas as pd
    data = app.create_sample_data()
    trap = data["Traps"][data["Traps"]["Product"] == "R1"].iloc[0]
    def window(wid, final, finding="Dead animal found", camera="No", review="Complete"):
        row = {c: "" for c in app.SHEETS["Windows"]}
        row.update({
            "Window ID": wid, "Trap ID": trap["Trap ID"], "Product": trap["Product"], "Build Version": trap["Build Version"],
            "Site ID": trap["Site ID"], "Status": "Closed", "Start Time": "2026-08-01 00:00:00", "End Time": "2026-08-02 00:00:00",
            "Finding At Close": finding, "Camera Assigned": camera, "Final Humane Kill": final, "Review Status": review,
        })
        return row
    rows = []
    rows += [window(f"K-YES-{i}", "Yes") for i in range(12)]
    rows += [window(f"K-NO-{i}", "No") for i in range(2)]
    rows += [window("K-WAIT", "Pending")]
    rows += [window("K-NOCARCASS", app.NOT_ASSESSED_NO_CARCASS)]
    rows += [window("K-ENDED", app.NOT_ASSESSED_TRIAL_ENDED)]
    rows += [window("CAM-UNRESOLVED", "", finding="Trap still set, no animal", camera="Yes", review="Unresolved")]
    data["Windows"] = pd.concat([data["Windows"], pd.DataFrame(rows)], ignore_index=True)
    app.save_data(data)
"""


def test_trial_performance_counts_the_not_assessed_kills_honestly(page: Page, tmp_path: Path) -> None:
    process, url, _ = _start(tmp_path, PERFORMANCE_SEED)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
        page.get_by_role("link", name="Trial performance", exact=True).click()
        expect(page.get_by_text("What is driving the result?", exact=True)).to_be_visible(timeout=30_000)
        _pick(page, "Trap type", "R1")
        expect(page.get_by_text("Kill outcome", exact=True)).to_be_visible(timeout=30_000)

        # 17 confirmed kills = 12 humane + 2 not humane + 1 awaiting + 2 not assessed.
        expect(page.get_by_text("86%", exact=True).first).to_be_visible(timeout=15_000)  # 12 of the 14 assessed
        expect(page.get_by_text("→ 1 kill awaiting final assessment — see Results needing attention", exact=True)).to_be_visible(timeout=15_000)
        expect(page.get_by_text(
            "2 kills counted but not assessed (1 no carcass, 1 trial ended) — not in the humane rate.", exact=True
        )).to_be_visible(timeout=15_000)
        expect(page.get_by_text("14 of 17", exact=True).first).to_be_visible(timeout=15_000)  # Kill assessments complete
        expect(page.get_by_text(
            "Unresolved: 1 — review given up on at trial end. Not counted as complete.", exact=True
        )).to_be_visible(timeout=15_000)
        assert (
            "Based on 14 of 17 confirmed kills with a completed necropsy assessment. "
            "All 17 count as kills; only assessed kills count toward the humane rate."
        ) in page.content()

        # The two not-assessed kills are not "incomplete results": 2 bad kills + 1 awaiting.
        expect(page.get_by_text("2 bad kills · 1 incomplete result", exact=True)).to_be_visible(timeout=15_000)
    finally:
        _stop(process)
