"""FIELD_SPEED_PHASE1_BRIEF.md Part B: the pure-navigation taps on the field
hot path render in a single script run. Measured with the speed probe: each
converted tap must log exactly one `complete` run and no `navigate` or
`rerun` run (before the change, "Start checking"/back/pause/exit logged a
`navigate` run plus a `complete` run, and "Check" logged `rerun`, `navigate`
and `complete`). Behaviour must be otherwise unchanged: same destinations,
one visit created, and the same page restored after a reload."""
from __future__ import annotations

import pandas as pd
import pytest
from playwright.sync_api import Page

from speed_nav_flow import kinds, run_flow
from test_speed_probe import ProbeApp, start_app, stop_app


@pytest.fixture
def probe_app(tmp_path):
    process, log_file, app = start_app(tmp_path, {"SPEED_PROBE": "1"})
    try:
        yield app
    finally:
        stop_app(process, log_file)


def test_hot_path_taps_render_in_one_run_and_restore_the_same_pages(page: Page, probe_app: ProbeApp) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    report = run_flow(page, probe_app)

    for tap in [
        "start_checking", "check_trap_1", "back_to_selector", "check_another",
        "back_again", "pause", "resume_checking", "check_before_exit", "exit_to_trap_sites",
    ]:
        assert kinds(report[tap]) == ["complete"], f"{tap} ran {kinds(report[tap])}: {report[tap]}"

    # "Start checking" now does its save inside the callback: that time is
    # attributed to the run that follows it, not lost.
    assert 'cb_ms=0' not in report["start_checking"][0]
    assert 'save_ms=0' not in report["start_checking"][0]

    # Restore behaviour after a dropped connection / reload is unchanged.
    assert report["_reload_on_check_page"] == "resume_prompt"
    assert report["_reload_on_visit_page"] == "trap_sites"
    assert report["_reload_on_trap_sites"] == "trap_sites"

    visits = pd.read_excel(probe_app.data_dir / "field_trial_data_v8_6_5.xlsx", sheet_name="Visits", dtype=str)
    assert len(visits) == 1 and visits.iloc[0]["Status"] == "In progress", "exactly one visit must have been created"
