"""QA brief F3-F7, the fixes from the owner's review of the Phase 2 screenshots.

F3 no blank gap between the phone hub's cards (desktop unchanged)      F4 primary buttons fill a phone, natural width on desktop
F5 "never checked" wording                                             F6 NZ day/month/year on the three journey date inputs
F7 Set up Preview warns, never blocks, when a declared build has no traps"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from journey_seed import END_SEED, JOURNEY_SEED  # noqa: E402
from test_trial_model_ui import _serve, _sheet  # noqa: E402
from test_trial_screens import _card, _decide_unresolvable, _home, _open_set_up, _tick, _to_end_trial_from_the_visit  # noqa: E402

PHONE, DESKTOP = {"width": 390, "height": 844}, {"width": 1280, "height": 900}


def _primary_widths(page: Page) -> list[tuple[str, int]]:
    return page.evaluate("""() => [...document.querySelectorAll('.st-key-r1_screen button[kind="primary"], .st-key-r1_screen button[kind="primaryFormSubmit"]')]
        .filter(b => b.getBoundingClientRect().width > 0).map(b => [b.innerText.trim(), Math.round(b.getBoundingClientRect().width)])""")


def _open_hub(page: Page, url: str) -> None:
    _home(page, url)
    _card(page, "Mangaroa Farm").get_by_role("button", name="Trial overview", exact=True).click()
    expect(page.get_by_text("Evidence waiting", exact=True)).to_be_visible(timeout=20_000)
    page.wait_for_timeout(600)


# --- F3 ---------------------------------------------------------------------------------------

def test_the_phone_hub_has_no_blank_gap_between_its_cards_and_desktop_is_unchanged(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, END_SEED) as url:
        page.set_viewport_size(PHONE)
        _open_hub(page, url)
        visits = page.locator('[class*="st-key-card_hub_visits"]').bounding_box()
        evidence = page.locator('[class*="st-key-card_hub_evidence"]').bounding_box()
        gap = evidence["y"] - (visits["y"] + visits["height"])
        assert 0 <= gap <= 20, f"the cards are {gap:.0f}px apart on a phone"
        page.set_viewport_size(DESKTOP); page.wait_for_timeout(800)
        visits = page.locator('[class*="st-key-card_hub_visits"]').bounding_box()
        evidence = page.locator('[class*="st-key-card_hub_evidence"]').bounding_box()
        assert evidence["x"] > visits["x"] + visits["width"], "on desktop the two cards are still side by side"


# --- F4 ---------------------------------------------------------------------------------------

def test_primary_buttons_fill_a_phone_and_keep_their_natural_width_on_desktop(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, JOURNEY_SEED) as url:
        page.set_viewport_size(PHONE)
        _open_set_up(page, url)
        seen = {}
        expect(page.get_by_role("button", name="Next: choose traps")).to_be_visible(timeout=20_000)
        seen["Next: choose traps"] = _primary_widths(page)
        page.get_by_role("button", name="Next: choose traps").click()
        expect(page.get_by_text("Set all unassigned to", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("radio", name="Build 4.3").first.click(); page.wait_for_timeout(400)
        seen["Preview activation"] = _primary_widths(page)
        page.get_by_role("button", name="Preview activation").click()
        expect(page.get_by_text("This trial", exact=True)).to_be_visible(timeout=20_000)
        seen["Start trial"] = _primary_widths(page)
        for name, widths in seen.items():
            assert widths and all(w >= 340 for _, w in widths), (name, widths)
        page.set_viewport_size(DESKTOP); page.wait_for_timeout(800)
        assert all(w <= 300 for _, w in _primary_widths(page)), "desktop keeps natural-width buttons"

    (tmp_path / "e").mkdir()
    with _serve(tmp_path / "e", END_SEED) as url:
        page.set_viewport_size(PHONE)
        _open_hub(page, url)
        widths = _primary_widths(page)
        assert widths and all(w >= 340 for _, w in widths), widths


# --- F5 / F6 ----------------------------------------------------------------------------------

def _date_values(page: Page) -> list[str]:
    page.locator('[data-testid="stDateInput"] input').first.wait_for(state="visible", timeout=20_000)
    return page.locator('[data-testid="stDateInput"] input').evaluate_all("els => els.map(e => e.value)")


def test_the_three_journey_date_inputs_show_new_zealand_day_month_year(page: Page, tmp_path: Path) -> None:
    nz = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, JOURNEY_SEED) as url:
        _open_set_up(page, url)
        assert _date_values(page) and all(nz.match(v) for v in _date_values(page)), ("Set up", _date_values(page))
        _home(page, url)
        _card(page, "Kaitoke Shed").get_by_role("button", name="Track as a trial", exact=True).click()
        expect(page.get_by_text("Builds currently running", exact=True)).to_be_visible(timeout=20_000)
        assert _date_values(page) and all(nz.match(v) for v in _date_values(page)), ("Track as a trial", _date_values(page))
    (tmp_path / "e").mkdir()
    with _serve(tmp_path / "e", END_SEED) as url:
        _to_end_trial_from_the_visit(page, url)
        # F5: the wording for a trap that has never been checked.
        expect(page.get_by_role("checkbox", name="R1-MAN-005 · never checked", exact=True)).to_be_checked()
        expect(page.get_by_text("last checked never", exact=False)).to_have_count(0)
        _decide_unresolvable(page)
        expect(page.get_by_text("Marked unresolvable", exact=True)).to_be_visible(timeout=20_000)
        _decide_unresolvable(page)
        page.get_by_role("button", name="Continue to preview").click()
        expect(page.get_by_text("What ending does", exact=True)).to_be_visible(timeout=20_000)
        assert _date_values(page) and all(nz.match(v) for v in _date_values(page)), ("End trial", _date_values(page))


# --- F7 ---------------------------------------------------------------------------------------

def test_the_warning_names_each_empty_declared_build_and_the_ones_that_will_be_recorded() -> None:
    script = """
        import json, app
        rows = lambda *builds: [{"Build": b} for b in builds]
        A, B, C = "R1 · R1 Build 4.3", "R1 · R1 Build 4.2", "R1 · R1 Build 4.1"
        print(json.dumps([
            app.unused_declared_builds_message([A, B], rows(A, A, A)),
            app.unused_declared_builds_message([A, B], rows(A, B)),
            app.unused_declared_builds_message([A, B, C], rows(A, A)),
            app.unused_declared_builds_message([A, B, C], rows(B, C)),
            app.unused_declared_builds_message([A], rows(A)),
        ]))
    """
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=tempfile.mkdtemp())
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    one_empty, none_empty, two_empty, first_empty, single = json.loads(result.stdout.strip().splitlines()[-1])
    assert one_empty == "Build 4.2 has no traps. This trial will only record Build 4.3."
    assert none_empty == "" and single == ""
    assert two_empty == "Build 4.2 and Build 4.1 have no traps. This trial will only record Build 4.3."
    assert first_empty == "Build 4.3 has no traps. This trial will only record Build 4.2 and Build 4.1."


def test_set_up_preview_warns_about_an_empty_declared_build_but_never_blocks(page: Page, tmp_path: Path) -> None:
    warning = "Build 4.2 has no traps. This trial will only record Build 4.3."
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, JOURNEY_SEED) as url:
        _open_set_up(page, url)
        _tick(page, "Build 4.2")
        page.get_by_role("button", name="Next: choose traps").click()
        expect(page.get_by_text("Set all unassigned to", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("radio", name="Build 4.3").first.click(); page.wait_for_timeout(400)  # everything on 4.3
        page.get_by_role("button", name="Preview activation").click()
        expect(page.get_by_text("This trial", exact=True)).to_be_visible(timeout=20_000)
        expect(page.get_by_text(warning, exact=True)).to_be_visible()
        assert page.get_by_role("button", name="Start trial", exact=True).is_enabled(), "a warning, not a block"
        # Move one trap onto 4.2 and the warning goes.
        page.get_by_role("button", name="Back to traps").click()
        expect(page.get_by_text("Set all unassigned to", exact=True)).to_be_visible(timeout=20_000)
        page.locator('[class*="st-key-seg_choosef_R1-MAN-NEW1"] button[role="radio"]').filter(has_text="Build 4.2").click(); page.wait_for_timeout(500)
        page.get_by_role("button", name="Preview activation").click()
        expect(page.get_by_text("This trial", exact=True)).to_be_visible(timeout=20_000)
        expect(page.get_by_text(warning, exact=True)).to_have_count(0)


# --- found in the QA brief's complete small trial: a trial ended straight after the last check ---------------------------

# The visit and its checks are stamped 30 seconds ahead of now, so the minute-truncated default end time is *always* earlier than the
# latest check (what happens when a trial is ended within a minute of the last check), whichever second the test runs in.
NOW_CHECKS_SEED = END_SEED.replace("app.dtstr(D(2026, 10, 5, 8))", "app.dtstr(app.now() + dt.timedelta(seconds=30))").replace("app.dtstr(D(2026, 10, 5, 9))", "app.dtstr(app.now() + dt.timedelta(seconds=30))")


def test_ending_a_trial_straight_after_the_last_check_never_ends_the_visit_before_it_started(page: Page, tmp_path: Path) -> None:
    import pandas as pd  # noqa: PLC0415
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, NOW_CHECKS_SEED) as url:
        _to_end_trial_from_the_visit(page, url)
        _decide_unresolvable(page)
        expect(page.get_by_text("Marked unresolvable", exact=True)).to_be_visible(timeout=20_000)
        _decide_unresolvable(page)
        page.get_by_role("button", name="Continue to preview").click()
        expect(page.get_by_text("What ending does", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("button", name="Confirm trial end").click()
        expect(page.get_by_text("Trial ended at Mangaroa Farm", exact=True)).to_be_visible(timeout=60_000)
        visits = _sheet(data_dir, "Visits"); visit = visits[visits["Status"] == "Partial"].iloc[0]
        assert pd.to_datetime(visit["End Time"]) >= pd.to_datetime(visit["Start Time"]), f"the visit ended before it started: {visit['Start Time']} -> {visit['End Time']}"
        windows = _sheet(data_dir, "Windows"); closed = windows[(windows["Site ID"] == "MAN") & (windows["End Time"] != "")]
        assert (pd.to_datetime(closed["End Time"]) >= pd.to_datetime(closed["Start Time"])).all(), "a window was closed before it opened"


# --- Set up after a trial that ended up to a minute ahead of now (the End default is rounded up to clear the last check) ----------

ENDED_AHEAD_SEED = JOURNEY_SEED + """
    d = app.load_data()
    ended = app.now() + dt.timedelta(seconds=30)
    d["Trials"].loc[d["Trials"]["Site ID"] == "MAN", "End Time"] = app.dtstr(ended)
    app.save_data(d)
"""


def test_set_up_defaults_to_a_start_no_earlier_than_the_previous_trial_ended(page: Page, tmp_path: Path) -> None:
    from datetime import datetime  # noqa: PLC0415
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, ENDED_AHEAD_SEED) as url:
        ended = datetime.strptime(str(_sheet(data_dir, "Trials").query("`Site ID` == 'MAN'").iloc[0]["End Time"]), "%Y-%m-%d %H:%M:%S")
        _open_set_up(page, url)
        clock = re.search(r"\d{2}:\d{2}", page.locator('[data-testid="stTimeInput"]').first.inner_text()).group(0)
        start = datetime.strptime(page.locator('[data-testid="stDateInput"] input').first.input_value() + " " + clock, "%d/%m/%Y %H:%M")
        assert start >= ended, f"Set up proposes {start} but the previous trial ended {ended}"
