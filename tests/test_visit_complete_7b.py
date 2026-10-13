"""Phase 7b, Visit complete (VisitComplete board): the confirmation after Finish site check is a summary (a check, the site, traps checked, kills and
time on site, what needs doing next, when the next visit is due), shown once on the page Finish already lands on (the trial hub at a tracked site,
Trap sites otherwise). Local test data only.

The numbers are worked out by visit_complete_summary() from the frames the run already holds; the pure part is tested in a subprocess."""
from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from journey_seed import END_SEED  # noqa: E402
from test_trial_model_ui import _serve  # noqa: E402
from test_trial_screens import _card, _home  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PHONE, DESKTOP = {"width": 414, "height": 896}, {"width": 1280, "height": 900}

# KAI is running with no trial record. A visit at it started 52 minutes ago, every trap checked, the first with a dead rat; two tasks came of it.
VISIT_AT_KAI = """
    d = app.load_data()
    kai = d["Traps"][(d["Traps"]["Site ID"] == "KAI") & (d["Traps"]["Status"] == "Active")]["Trap ID"].tolist()
    vid = "VIS-KAI-NOW"; start = START_EXPR
    d["Visits"] = pd.concat([d["Visits"], pd.DataFrame([[vid, "KAI", "Op", app.dtstr(start), "", "In progress", ""]], columns=app.SHEETS["Visits"])], ignore_index=True)
    for i, t in enumerate(kai):
        row = {c: "" for c in app.SHEETS["Checks"]}
        row.update({"Check ID": "C-K-" + t, "Visit ID": vid, "Trap ID": t, "Check Time": app.dtstr(start + dt.timedelta(minutes=8 * (i + 1))),
                    "Finding": "Dead animal found" if (i == 0 and KILL) else "Trap still set, no animal", "Species": "Rat" if (i == 0 and KILL) else ""})
        d["Checks"] = pd.concat([d["Checks"], pd.DataFrame([row])], ignore_index=True)
"""
MIDNIGHT = "app.now().replace(hour=0, minute=0, second=0, microsecond=0)"
UNTRACKED = END_SEED + "    KILL = True\n" + VISIT_AT_KAI.replace("START_EXPR", f"max(app.now() - dt.timedelta(minutes=52), {MIDNIGHT})") + """
    app.add_followup(d, "Necropsy review", "KAI", kai[0], vid, "W-K", "KAI-014", "Dead animal collected", "d", "Normal")
    app.add_followup(d, "Camera review", "KAI", kai[0], vid, "W-K", "KAI-014", "Dead animal found", "d", "Normal")
    app.save_data(d)
"""
# MAN is running a trial; its visit has all five traps checked, started 70 minutes ago, and five camera reviews came of it.
TRACKED = END_SEED.replace("for t in r1[:3]:", "for t in r1:") + """
    d = app.load_data()
    d["Visits"].loc[d["Visits"]["Visit ID"] == "VIS-WALK-1", "Start Time"] = app.dtstr(app.now() - dt.timedelta(minutes=70))
    for t in r1:
        app.add_followup(d, "Camera review", "MAN", t, "VIS-WALK-1", "W-" + t, "", "Trap still set, no animal", "d", "Normal")
    app.save_data(d)
"""
# A visit that began two days ago, no kill, no tasks: the least a summary says.
LEAST = END_SEED + "    KILL = False\n" + VISIT_AT_KAI.replace("START_EXPR", "app.now() - dt.timedelta(days=2)") + "    app.save_data(d)\n"

SUMMARY = """() => { const r = document.querySelector('.r1-vc'); if (!r) return null;
  const text = e => e.innerText.replace(/\\s+/g, ' ').trim();
  return {title: text(r.querySelector('.r1-vc-title')), site: text(r.querySelector('.r1-vc-site')),
          stats: [...r.querySelectorAll('.r1-vc-stats > div')].map(text), needs: [...r.querySelectorAll('.r1-vc-row')].map(text),
          heading: r.querySelector('.r1-vc-needs h3') ? text(r.querySelector('.r1-vc-needs h3')) : null, next: r.querySelector('.r1-vc-next') ? text(r.querySelector('.r1-vc-next')) : null,
          width: Math.round(r.getBoundingClientRect().width), visible: r.getBoundingClientRect().height > 100}; }"""
NEXT_DUE = re.compile(r"^Next visit due (Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2}\.$")


def _check_on_site(stats: list, started_minutes_ago: int) -> None:
    """The seeds start a visit N minutes ago, but never before NZ midnight (a visit across midnight has no On site, which the unit test covers),
    so what On site should read depends on the NZ clock when the test runs."""
    now = datetime.now(ZoneInfo("Pacific/Auckland"))
    want = min(started_minutes_ago, now.hour * 60 + now.minute)
    if want < 5:
        return  # too close to midnight to say what a minute-rounded figure should be
    shown = [s for s in stats if s.endswith(" On site")]
    assert len(shown) == 1, stats
    hours, minutes = re.fullmatch(r"(?:(\d+) h )?(\d+) min On site", shown[0]).groups()
    assert abs(int(hours or 0) * 60 + int(minutes) - want) <= 3, (shown, want)


def _finish(page: Page, url: str, site_id: str) -> None:
    _home(page, url)
    page.locator(f".st-key-card_site_{site_id}").get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).click()
    finish = page.get_by_role("button", name=re.compile(r"^Finish site check"))
    expect(finish).to_be_visible(timeout=30_000)
    assert finish.is_enabled(), "every trap is checked in this seed"
    finish.click()
    expect(page.get_by_text("Visit complete", exact=True)).to_be_visible(timeout=40_000)


def test_finishing_an_untracked_site_shows_the_summary_on_trap_sites(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, UNTRACKED) as url:
        _finish(page, url, "KAI")
        v = page.evaluate(SUMMARY)
        assert v["title"] == "Visit complete" and v["site"] == "Kaitoke Shed" and v["visible"], v
        assert v["stats"][0] == "4 Traps checked" and v["stats"][1] == "1 Kill", v["stats"]
        _check_on_site(v["stats"], 52)
        assert v["heading"] == "Needs doing next"
        assert v["needs"] == ["Necropsy review R1-KAI-001 · Bag KAI-014", "Camera review R1-KAI-001 · footage not yet reviewed"], v["needs"]
        assert NEXT_DUE.match(v["next"]), v["next"]
        # it landed where it always did (Trap sites), and the old one-line message and its repeated count are gone
        expect(page.get_by_role("heading", name="Trap sites", exact=True)).to_be_visible()
        body = page.locator("body").inner_text()
        assert "All 4 traps were checked" not in body and "site check completed" not in body


def test_finishing_a_tracked_site_shows_the_summary_on_the_hub_with_the_tasks_grouped(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, TRACKED) as url:
        _finish(page, url, "MAN")
        expect(page.get_by_text("Evidence waiting", exact=True)).to_be_visible(timeout=20_000)  # the hub, as before
        v = page.evaluate(SUMMARY)
        assert v["stats"][:2] == ["5 Traps checked", "0 Kills"], v["stats"]
        _check_on_site(v["stats"], 70)
        assert v["needs"] == ["Camera review 5 traps · footage not yet reviewed"], "five tasks of one kind are one row, not five"


def test_the_least_a_summary_says_leaves_out_what_it_cannot_say_truthfully(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, LEAST) as url:
        _finish(page, url, "KAI")
        v = page.evaluate(SUMMARY)
        assert v["stats"] == ["4 Traps checked", "0 Kills"], "a visit that crossed a calendar day has no honest time on site, so none is shown"
        assert v["needs"] == [] and v["heading"] is None, "nothing to do: no list and no heading"
        assert NEXT_DUE.match(v["next"])


def test_the_summary_is_shown_once_and_fits_a_phone_and_a_desktop(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, UNTRACKED) as url:
        page.set_viewport_size(PHONE)
        _finish(page, url, "KAI")
        assert page.evaluate(SUMMARY)["width"] <= 414
        page.set_viewport_size(DESKTOP); page.wait_for_timeout(500)
        assert page.evaluate(SUMMARY)["width"] <= 560, "capped on a desktop"
        page.reload(wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="Trap sites", exact=True)).to_be_visible(timeout=30_000)
        page.wait_for_timeout(800)
        assert page.evaluate(SUMMARY) is None, "a one-off: it does not come back on the next load"


# --- the numbers, without a browser --------------------------------------------------------------------------------------

def _summary(tmp_path: Path, body: str) -> dict:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir), STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
    code = textwrap.dedent("""
        import datetime as dt, json, logging, os, sys
        logging.disable(logging.CRITICAL); sys.path.insert(0, os.getcwd())
        import pandas as pd, app
        data = {k: v.copy() for k, v in app.load_data().items()}
        sid = data["Sites"].iloc[0]["Site ID"]
        def visit(vid, minutes, status="Complete"):
            start = app.now() - dt.timedelta(minutes=minutes)
            data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([[vid, sid, "Op", app.dtstr(start), app.dtstr(app.now()), status, ""]], columns=app.SHEETS["Visits"])], ignore_index=True)
        def check(vid, trap, finding="Trap still set, no animal"):
            row = {c: "" for c in app.SHEETS["Checks"]}; row.update({"Check ID": f"C-{vid}-{trap}-{len(data['Checks'])}", "Visit ID": vid, "Trap ID": trap, "Finding": finding})
            data["Checks"] = pd.concat([data["Checks"], pd.DataFrame([row])], ignore_index=True)
    """) + textwrap.dedent(body) + "\nprint('RESULT' + json.dumps(out))\n"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2500:]
    return json.loads([ln for ln in result.stdout.splitlines() if ln.startswith("RESULT")][-1][6:])


def test_time_on_site_is_shown_in_minutes_then_hours_and_left_out_when_the_visit_crossed_a_calendar_day(tmp_path: Path) -> None:
    """The rule: shown when the visit lasted a minute or more and began and finished on the same NZ calendar day; no hour limit."""
    out = _summary(tmp_path, """
        out = {}
        def visit_at(vid, start, end):
            data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([[vid, sid, "Op", start, end, "Complete", ""]], columns=app.SHEETS["Visits"])], ignore_index=True)
        for vid, start, end in (("V0", "2026-10-05 08:00:00", "2026-10-05 08:00:20"), ("V1", "2026-10-05 08:00:00", "2026-10-05 08:01:00"),
                                ("V59", "2026-10-05 08:00:00", "2026-10-05 08:59:00"), ("V60", "2026-10-05 08:00:00", "2026-10-05 09:00:00"),
                                ("V61", "2026-10-05 08:00:00", "2026-10-05 09:01:00"), ("V12h30", "2026-10-05 08:00:00", "2026-10-05 20:30:00"),
                                ("VLATE", "2026-10-05 00:00:00", "2026-10-05 23:59:00"), ("VMID", "2026-10-05 23:30:00", "2026-10-06 00:10:00")):
            visit_at(vid, start, end); check(vid, "T1")
            out[vid] = [s for s in app.visit_complete_summary(data, sid, vid)["stats"] if s[1] == "On site"]
    """)
    assert out == {"V0": [], "V1": [["1 min", "On site"]], "V59": [["59 min", "On site"]], "V60": [["1 h 0 min", "On site"]], "V61": [["1 h 1 min", "On site"]],
                   "V12h30": [["12 h 30 min", "On site"]], "VLATE": [["23 h 59 min", "On site"]], "VMID": []}, out


def test_kills_count_traps_not_checks_and_tasks_group_by_kind_with_the_right_captions(tmp_path: Path) -> None:
    out = _summary(tmp_path, """
        visit("V", 30)
        check("V", "T1", "Dead animal found"); check("V", "T1", "Dead animal found"); check("V", "T2", "Dead animal found"); check("V", "T3")
        app.add_followup(data, "Necropsy review", sid, "T1", "V", "W1", "", "Dead animal collected", "d", "Normal")   # one, no bag
        app.add_followup(data, "Camera review", sid, "T1", "V", "W1", "", "x", "d", "Normal")
        app.add_followup(data, "Camera review", sid, "T2", "V", "W2", "", "x", "d", "Normal")
        app.add_followup(data, "Trap not ready", sid, "T3", "V", "W3", "", "Lure gone", "d", "High")
        app.add_followup(data, "Camera review", sid, "T9", "OTHER", "W9", "", "x", "d", "Normal")                       # another visit's task
        done = app.add_followup(data, "Camera issue", sid, "T4", "V", "W4", "", "x", "d", "Normal")
        data["Followups"].loc[data["Followups"]["Follow-up Type"] == "Camera issue", "Status"] = "Complete"             # already done
        s = app.visit_complete_summary(data, sid, "V")
        out = {"stats": s["stats"][:2], "needs": s["needs"]}
    """)
    assert out["stats"] == [["3", "Traps checked"], ["2", "Kills"]], out["stats"]
    assert out["needs"] == [["bag", "Necropsy review", "T1"], ["camera", "Camera review", "2 traps · footage not yet reviewed"], ["warn-circle", "Trap not ready", "T3 · lure gone"]], out["needs"]
