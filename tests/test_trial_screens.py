"""Phase 2 (TRIAL_LIFECYCLE_BRIEF.md): the trial journey in a real browser.

Trap sites card states, Set up (two batched steps, preview, atomic confirm), Track as a trial,
the hub, End trial (decision queue, unresolvable confirmation, preview, atomic confirm), the
visit page's new action and landing, and the return path from a review opened in End trial.
Data is local test data only (see journey_seed.py)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from journey_seed import END_SEED, JOURNEY_SEED  # noqa: E402
from test_trial_model_ui import _serve, _sheet  # noqa: E402

ALL_CHECKED_SEED = END_SEED.replace("for t in r1[:3]:", "for t in r1:")


def _tick(page: Page, label: str) -> None:
    box = page.get_by_role("checkbox", name=label, exact=True)
    box.focus()
    page.keyboard.press("Space")
    page.wait_for_timeout(250)


def _choose(page: Page, label: str, option: str) -> None:
    """Pick an option in a Streamlit selectbox. The list sometimes needs a second tap if the page was
    still settling from a rerun, so it reopens the box until the option is on screen."""
    combo = page.get_by_role("combobox", name=re.compile(label))
    target = page.get_by_role("option").filter(has_text=re.compile(rf"^{re.escape(option)}$")).first
    for _ in range(4):
        combo.click()
        try:
            target.wait_for(state="visible", timeout=3_000)
            break
        except Exception:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    target.click()


def _home(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    page.wait_for_timeout(800)


def _card(page: Page, site_name: str):
    """The Trap sites card for a site: the nearest ancestor of its name that holds buttons."""
    return page.get_by_text(site_name, exact=True).first.locator("xpath=ancestor::div[.//button][1]")


def _only_ever_one_open_window(data_dir: Path, trap_ids) -> None:
    windows = _sheet(data_dir, "Windows")
    for t in trap_ids:
        assert ((windows["Trap ID"] == t) & (windows["Status"] == "Open")).sum() == 1, t


# --- Trap sites card -----------------------------------------------------------------------

def test_the_trap_sites_card_shows_the_right_state_and_buttons(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, JOURNEY_SEED) as url:
        _home(page, url)
        mangaroa, kaitoke = _card(page, "Mangaroa Farm"), _card(page, "Kaitoke Shed")
        # no active traps, no trial: "No trial running" and Start trial
        expect(mangaroa.get_by_text("No trial running", exact=False)).to_be_visible()
        expect(mangaroa.get_by_role("button", name="Start trial", exact=True)).to_be_visible()
        # running with no trial record: the note, checking still available, and Track as a trial
        expect(kaitoke.get_by_text("Not tracked as a trial yet — checks are recorded, but results aren't tied to a trial.", exact=True)).to_be_visible()
        expect(kaitoke.get_by_role("button", name="Start checking", exact=True)).to_be_visible()
        expect(kaitoke.get_by_role("button", name="Track as a trial", exact=True)).to_be_visible()
        assert kaitoke.get_by_role("button", name="Trial overview").count() == 0


def test_a_site_with_an_open_trial_offers_the_hub_and_no_untracked_note(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        card = _card(page, "Mangaroa Farm")
        expect(card.get_by_role("button", name="Trial overview", exact=True)).to_be_visible()
        expect(card.get_by_role("button", name="Resume checking", exact=True)).to_be_visible()
        assert card.get_by_text("Not tracked as a trial yet", exact=False).count() == 0
        assert card.get_by_role("button", name="Track as a trial").count() == 0


# --- Set up ------------------------------------------------------------------------------------

def _open_set_up(page: Page, url: str) -> None:
    _home(page, url)
    _card(page, "Mangaroa Farm").get_by_role("button", name="Start trial", exact=True).click()
    expect(page.get_by_text("Builds this trial compares", exact=True)).to_be_visible(timeout=20_000)


def test_set_up_two_steps_preview_and_one_atomic_confirm(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, JOURNEY_SEED) as url:
        trials_before = len(_sheet(data_dir, "Trials"))
        _open_set_up(page, url)
        # The previous trial's builds are pre-selected (the roster carries over); add the second declared build.
        expect(page.get_by_role("checkbox", name="Build 4.3", exact=True)).to_be_checked()
        _tick(page, "Build 4.2")
        page.get_by_role("button", name="Next: choose traps").click()
        expect(page.get_by_text("Set all unassigned to", exact=True)).to_be_visible(timeout=20_000)
        for heading in ("Carried over", "New", "Relocated"):
            expect(page.get_by_text(heading, exact=True)).to_be_visible()
        # Two carried-over traps were on a build that is not declared: they say so, and nothing is silently defaulted.
        expect(page.get_by_text("not in this trial", exact=False)).to_have_count(2)

        # Submitting with those two unassigned is refused, lists them, and writes nothing.
        page.get_by_role("button", name="Preview activation").click()
        expect(page.get_by_text("2 traps need a build before you can continue: R1-MAN-005, R1-MAN-006", exact=True)).to_be_visible(timeout=20_000)
        assert len(_sheet(data_dir, "Trials")) == trials_before and (_sheet(data_dir, "Traps").set_index("Trap ID").loc["R1-MAN-005", "Status"] == "Inactive")

        # The "Set all unassigned to" helper fills the gaps in one tap.
        page.get_by_role("radio", name="Build 4.3").first.click()
        page.wait_for_timeout(400)
        page.get_by_role("button", name="Preview activation").click()
        expect(page.get_by_text("This trial", exact=True)).to_be_visible(timeout=20_000)
        expect(page.get_by_role("button", name="Start trial", exact=True)).to_be_visible()
        assert len(_sheet(data_dir, "Trials")) == trials_before, "nothing is written until Confirm"
        page.get_by_role("button", name="Start trial", exact=True).click()
        expect(page.get_by_text("7 traps are active.", exact=True)).to_be_visible(timeout=60_000)

        trials = _sheet(data_dir, "Trials")
        trial = trials[trials["Status"] == "Open"].iloc[0]
        assert trial["Site ID"] == "MAN" and trial["Origin"] == "Started" and trial["Declared Builds"] == "R1 · R1 Build 4.3; R1 · R1 Build 4.2"
        traps = _sheet(data_dir, "Traps").set_index("Trap ID")
        for t in ("R1-MAN-001", "R1-MAN-002", "R1-MAN-003", "R1-MAN-005", "R1-MAN-006", "R1-MAN-NEW1", "R1-MAN-NEW2"):
            assert traps.loc[t, "Status"] == "Active" and traps.loc[t, "Site ID"] == "MAN", t
            assert traps.loc[t, "Build Version"] == "R1 Build 4.3", t
        assert traps.loc["R1-WAI-001", "Status"] == "Inactive" and traps.loc["R1-WAI-001", "Site ID"] == "WAI", "an unticked relocatable trap stays where it was"
        windows = _sheet(data_dir, "Windows")
        open_windows = windows[(windows["Status"] == "Open") & (windows["Site ID"] == "MAN")]
        assert len(open_windows) == 7 and set(open_windows["Trial ID"]) == {trial["Trial ID"]}
        _only_ever_one_open_window(data_dir, open_windows["Trap ID"])
        audit = _sheet(data_dir, "Audit Log")
        assert "Trial started at site" in set(audit["Reason"])

        # The hub is the next stop.
        page.get_by_role("button", name="Go to trial").click()
        expect(page.get_by_text("Evidence waiting", exact=True)).to_be_visible(timeout=20_000)
        expect(page.get_by_text("Trial day", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Start checking", exact=True)).to_be_visible()


def test_a_forced_failure_during_set_up_confirm_leaves_the_workbook_untouched(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, JOURNEY_SEED, {"R1M1_TEST_FAIL_TRIAL_ACTION": "set_up:2"}) as url:
        before = {n: _sheet(data_dir, n) for n in ("Trials", "Traps", "Windows", "Audit Log")}
        _open_set_up(page, url)
        page.get_by_role("button", name="Next: choose traps").click()
        expect(page.get_by_text("Set all unassigned to", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("radio", name="Build 4.3").first.click()
        page.wait_for_timeout(400)
        page.get_by_role("button", name="Preview activation").click()
        expect(page.get_by_text("This trial", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("button", name="Start trial", exact=True).click()
        expect(page.get_by_text("The trial has not started and every trap is as it was.", exact=False)).to_be_visible(timeout=60_000)
        for name, frame in before.items():
            pd.testing.assert_frame_equal(_sheet(data_dir, name), frame, obj=name)


def test_set_up_step_one_asks_for_one_to_three_builds(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, JOURNEY_SEED) as url:
        _open_set_up(page, url)
        _tick(page, "Build 4.3")  # untick the pre-selected build
        page.get_by_role("button", name="Next: choose traps").click()
        expect(page.get_by_text("A trial compares 1 to 3 builds.", exact=True)).to_be_visible(timeout=20_000)
        expect(page.get_by_text("Set all unassigned to", exact=True)).to_have_count(0)


# --- Track as a trial --------------------------------------------------------------------------------

def test_track_as_a_trial_previews_then_tags_exactly_what_it_showed(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, JOURNEY_SEED) as url:
        windows_before = _sheet(data_dir, "Windows")
        _home(page, url)
        _card(page, "Kaitoke Shed").get_by_role("button", name="Track as a trial", exact=True).click()
        expect(page.get_by_text("Builds currently running", exact=True)).to_be_visible(timeout=20_000)
        preview = page.get_by_text(re.compile(r"^\d+ across \d+ traps?$")).first
        expect(preview).to_be_visible()
        planned, traps_tagged = (int(x) for x in re.match(r"(\d+) across (\d+)", preview.inner_text()).groups())
        assert planned >= 1
        page.get_by_role("button", name="Track as trial", exact=True).click()
        expect(page.get_by_text("is tracked as a trial", exact=False)).to_be_visible(timeout=60_000)
        expect(page.get_by_text(f"{planned} windows tagged across {traps_tagged} trap", exact=False)).to_be_visible()
        trials = _sheet(data_dir, "Trials")
        trial = trials[(trials["Site ID"] == "KAI") & (trials["Status"] == "Open")].iloc[0]
        assert trial["Origin"] == "Adopted"
        windows = _sheet(data_dir, "Windows")
        tagged = windows[windows["Trial ID"] == trial["Trial ID"]]
        assert len(tagged) == planned and tagged["Trap ID"].nunique() == traps_tagged
        assert set(tagged["Site ID"]) == {"KAI"}
        other_cols = [c for c in windows.columns if c != "Trial ID"]
        pd.testing.assert_frame_equal(windows[other_cols], windows_before[other_cols], obj="adoption changes nothing but the stamp")


# --- End trial -----------------------------------------------------------------------------------------

def _to_end_trial_from_the_visit(page: Page, url: str) -> None:
    _home(page, url)
    _card(page, "Mangaroa Farm").get_by_role("button", name="Resume checking", exact=True).click()
    expect(page.get_by_text("Site check actions", exact=True)).to_be_visible(timeout=20_000)
    page.get_by_role("button", name=re.compile("Finish visit and end trial")).click()
    expect(page.get_by_text("Needs your decision", exact=True)).to_be_visible(timeout=20_000)


def _decide_unresolvable(page: Page) -> None:
    page.get_by_role("button", name="Decide").first.click()
    page.get_by_role("button", name=re.compile("Mark unresolvable")).first.click()
    expect(page.get_by_text("This gives up real trial evidence.", exact=False)).to_be_visible(timeout=20_000)
    mark = page.get_by_role("button", name=re.compile(r"^Mark unresolvable")).last
    assert mark.is_disabled(), "a single tap must never be enough: the confirmation has to be ticked first"
    _tick(page, "I understand this evidence will not be assessed.")
    mark.click()


def test_end_trial_from_a_partial_visit_resolves_everything_in_one_atomic_save(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, END_SEED) as url:
        _to_end_trial_from_the_visit(page, url)
        expect(page.get_by_text("This visit will close as Partial", exact=True)).to_be_visible()
        expect(page.get_by_text("3 of 5 traps checked.", exact=True)).to_be_visible()
        # Hardware tasks resolve themselves; evidence reviews need a decision; Continue says why it is disabled.
        expect(page.get_by_text("Trap not ready · R1-MAN-003 — removed at trial end", exact=True)).to_be_visible()
        expect(page.get_by_text("Camera issue · R1-MAN-002 — removed at trial end", exact=True)).to_be_visible()
        assert page.get_by_role("button", name="Continue to preview").is_disabled()
        expect(page.get_by_text("Make a decision on 2 reviews to continue.", exact=True)).to_be_visible()
        # Final-period camera review: ticked by default for the unchecked camera trap; the no-camera trap only gets a note.
        expect(page.get_by_role("checkbox", name="R1-MAN-005 · never checked", exact=True)).to_be_checked()
        expect(page.get_by_text("no camera, so a physical check is the only review", exact=False)).to_be_visible()
        before = {n: _sheet(data_dir, n) for n in ("Traps", "Windows", "Followups", "Trials", "Visits")}

        _decide_unresolvable(page)
        expect(page.get_by_text("Marked unresolvable", exact=True)).to_be_visible(timeout=20_000)
        _decide_unresolvable(page)
        expect(page.get_by_role("button", name="Continue to preview")).to_be_enabled(timeout=20_000)
        for name, frame in before.items():
            pd.testing.assert_frame_equal(_sheet(data_dir, name), frame, obj=f"{name} (a decision writes nothing until Confirm)")
        page.get_by_role("button", name="Continue to preview").click()
        expect(page.get_by_text("What ending does", exact=True)).to_be_visible(timeout=20_000)
        expect(page.get_by_text("Partial", exact=True)).to_be_visible()
        page.get_by_role("button", name="Confirm trial end").click()
        expect(page.get_by_text("Trial ended at Mangaroa Farm", exact=True)).to_be_visible(timeout=60_000)

        trial = _sheet(data_dir, "Trials").iloc[0]
        assert trial["Status"] == "Ended" and trial["End Time"]
        traps = _sheet(data_dir, "Traps")
        assert set(traps[traps["Site ID"] == "MAN"]["Status"]) == {"Inactive"}
        followups = _sheet(data_dir, "Followups").set_index("Follow-up Type")
        by_type = _sheet(data_dir, "Followups").groupby("Follow-up Type")["Status"].apply(list).to_dict()
        assert by_type["Necropsy review"] == ["Unresolvable — trial ended before review"]
        assert sorted(by_type["Camera review"]) == ["Open", "Unresolvable — trial ended before review"], "the new final-period review stays open"
        assert by_type["Trap not ready"] == ["Resolved — removed at trial end"] and by_type["Camera issue"] == ["Resolved — removed at trial end"]
        windows = _sheet(data_dir, "Windows").set_index("Window ID")
        assert windows.loc["W-KILL-1", "Review Status"] == "Unresolved" and windows.loc["W-KILL-1", "Final Humane Kill"] == "Not assessed — trial ended"
        visit = _sheet(data_dir, "Visits").set_index("Visit ID").loc["VIS-WALK-1"]
        assert visit["Status"] == "Partial" and visit["Notes"] == "Partial: 3 of 5 traps checked at trial end"
        assert not ((windows["Status"] == "Open") & (windows["Site ID"] == "MAN")).any(), "every window of the site closed"

        # The site is back to "No trial running": the card offers Start trial, and Next due was not reset by the Partial visit.
        page.get_by_role("button", name="Trap sites", exact=True).click()
        expect(_card(page, "Mangaroa Farm").get_by_role("button", name="Start trial", exact=True)).to_be_visible(timeout=20_000)

        # Trial Performance reports the given-up evidence honestly: a kill counted but not assessed, and an
        # unresolved review that is not counted as complete.
        page.get_by_role("link", name="Trial performance").click()
        expect(page.get_by_text("Trap type", exact=True)).to_be_visible(timeout=30_000)
        page.wait_for_timeout(1000)
        _choose(page, "Trap type", "R1")
        expect(page.get_by_text("1 kill counted but not assessed (1 trial ended) — not in the humane rate.", exact=True)).to_be_visible(timeout=30_000)
        expect(page.get_by_text("Unresolved: 1 — review given up on at trial end. Not counted as complete.", exact=True)).to_be_visible()
        assert page.get_by_text("awaiting final assessment", exact=False).count() == 0, "the kill no longer sits in the awaiting callout"


def test_end_trial_reaches_the_follow_up_form_and_returns_to_end_trial(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, END_SEED) as url:
        _to_end_trial_from_the_visit(page, url)
        # The first row is the camera review.
        page.get_by_role("button", name="Decide").first.click()
        expect(page.get_by_text("Reviewing 1 of 2", exact=False)).to_be_visible(timeout=20_000)
        page.get_by_role("button", name="Review now", exact=True).click()
        expect(page.get_by_text("Complete this review", exact=True)).to_be_visible(timeout=20_000)
        # Opened from End trial, the way back names End trial, not the task list.
        expect(page.get_by_role("button", name="← Back to End trial")).to_be_visible()
        page.get_by_role("button", name="← Back to End trial").click()
        expect(page.get_by_text("Needs your decision", exact=True)).to_be_visible(timeout=30_000)
        # Resolve the camera review for real: it saves, and we land back in End trial with that task gone.
        page.get_by_role("button", name="Decide").first.click()
        page.get_by_role("button", name="Review now", exact=True).click()
        expect(page.get_by_text("Complete this review", exact=True)).to_be_visible(timeout=20_000)
        page.wait_for_timeout(1500)
        _choose(page, "Camera evidence usable", "No")
        page.get_by_role("button", name="Save camera review").click()
        expect(page.get_by_text("Needs your decision", exact=True)).to_be_visible(timeout=60_000)
        expect(page.get_by_text("Camera review", exact=True)).to_have_count(0)
        expect(page.get_by_text("Necropsy review", exact=True)).to_be_visible()
        fu = _sheet(data_dir, "Followups")
        assert fu[fu["Follow-up Type"] == "Camera review"].iloc[0]["Status"] == "Complete"


def test_the_hub_disables_end_trial_mid_visit_and_says_why(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        _card(page, "Mangaroa Farm").get_by_role("button", name="Trial overview", exact=True).click()
        expect(page.get_by_text("Evidence waiting", exact=True)).to_be_visible(timeout=20_000)
        assert page.get_by_role("button", name="End trial…").is_disabled()
        expect(page.get_by_text("A visit is in progress.", exact=False)).to_be_visible()
        expect(page.get_by_role("button", name="Resume checking", exact=True)).to_be_visible()
        # Counts are site-wide: the camera and necropsy reviews on the kill.
        expect(page.get_by_text("Necropsy review", exact=True)).to_be_visible()


def test_finish_site_check_lands_on_the_hub_at_a_tracked_site(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, ALL_CHECKED_SEED) as url:
        _home(page, url)
        _card(page, "Mangaroa Farm").get_by_role("button", name="Resume checking", exact=True).click()
        expect(page.get_by_text("Site check actions", exact=True)).to_be_visible(timeout=20_000)
        assert page.get_by_role("button", name="Finish site check", exact=True).is_enabled()
        page.get_by_role("button", name="Finish site check", exact=True).click()
        expect(page.get_by_text("site check completed", exact=False)).to_be_visible(timeout=30_000)
        expect(page.get_by_text("Evidence waiting", exact=True)).to_be_visible(timeout=20_000)
        visit = _sheet(data_dir, "Visits").set_index("Visit ID").loc["VIS-WALK-1"]
        assert visit["Status"] == "Complete"


def test_the_visit_page_offers_finish_visit_and_end_trial_only_with_a_check_at_a_tracked_site(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        _card(page, "Mangaroa Farm").get_by_role("button", name="Resume checking", exact=True).click()
        expect(page.get_by_text("Site check actions", exact=True)).to_be_visible(timeout=20_000)
        assert page.get_by_role("button", name="Finish site check", exact=True).is_disabled(), "ordinary visits keep the all-traps rule"
        expect(page.get_by_role("button", name=re.compile("Finish visit and end trial"))).to_be_visible()
        expect(page.get_by_role("button", name="Pause and return to Trap sites")).to_be_visible()


# --- first viewport (field standard 8) -------------------------------------------------------------------

@pytest.mark.parametrize("viewport", [{"width": 414, "height": 896}])
def test_the_required_actions_are_in_the_first_viewport(page: Page, tmp_path: Path, viewport: dict) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(viewport)
    with _serve(data_dir, END_SEED) as url:
        _home(page, url)
        _card(page, "Mangaroa Farm").get_by_role("button", name="Trial overview", exact=True).click()
        expect(page.get_by_text("Evidence waiting", exact=True)).to_be_visible(timeout=20_000)
        for button in ("Resume checking",):
            box = page.get_by_role("button", name=button, exact=True).bounding_box()
            assert box and box["y"] + box["height"] <= viewport["height"], f"hub: {button} must be on the first screen"
        page.get_by_role("button", name="Resume checking", exact=True).click()
        expect(page.get_by_text("Site check actions", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("button", name=re.compile("Finish visit and end trial")).click()
        expect(page.get_by_text("Needs your decision", exact=True)).to_be_visible(timeout=20_000)
        decide = page.get_by_role("button", name="Decide").first.bounding_box()
        assert decide and decide["y"] + decide["height"] <= viewport["height"], "End trial: the decision list is on the first screen"
    data_dir2 = tmp_path / "d2"; data_dir2.mkdir()
    with _serve(data_dir2, JOURNEY_SEED) as url:
        _open_set_up(page, url)
        nxt = page.get_by_role("button", name="Next: choose traps").bounding_box()
        assert nxt and nxt["y"] + nxt["height"] <= viewport["height"], "Set up step 1: Next is on the first screen"


# --- Undo (Phase 3) ----------------------------------------------------------------------------------------

def _set_up_to_the_result(page: Page, url: str) -> None:
    _open_set_up(page, url)
    page.get_by_role("button", name="Next: choose traps").click()
    expect(page.get_by_text("Set all unassigned to", exact=True)).to_be_visible(timeout=20_000)
    page.get_by_role("radio", name="Build 4.3").first.click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="Preview activation").click()
    expect(page.get_by_text("This trial", exact=True)).to_be_visible(timeout=20_000)
    page.get_by_role("button", name="Start trial", exact=True).click()
    expect(page.get_by_text("Undo ends when you leave this screen or lock your phone.", exact=True)).to_be_visible(timeout=60_000)


def test_undo_from_the_set_up_result_screen_restores_the_workbook(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, JOURNEY_SEED) as url:
        before = {n: _sheet(data_dir, n) for n in ("Trials", "Traps", "Windows", "Followups", "Visits", "Checks")}
        _set_up_to_the_result(page, url)
        assert (_sheet(data_dir, "Trials")["Status"] == "Open").any()
        page.get_by_role("button", name="Undo this action").click()
        expect(page.get_by_text("Everything this action changed has been put back.", exact=True)).to_be_visible(timeout=60_000)
        for name, frame in before.items():
            pd.testing.assert_frame_equal(_sheet(data_dir, name), frame, obj=f"{name} after undo")
        audit = _sheet(data_dir, "Audit Log")
        assert audit["Reason"].str.startswith("Undo: ").any(), "the undo is itself recorded"
        # Undo is not offered again, and not after leaving the screen.
        assert page.get_by_role("button", name="Undo this action").count() == 0
        page.get_by_role("button", name="Trap sites", exact=True).click()
        expect(_card(page, "Mangaroa Farm").get_by_role("button", name="Start trial", exact=True)).to_be_visible(timeout=20_000)


def test_undo_is_gone_once_the_operator_leaves_the_result_screen(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, JOURNEY_SEED) as url:
        _set_up_to_the_result(page, url)
        page.get_by_role("button", name="Go to trial").click()
        expect(page.get_by_text("Evidence waiting", exact=True)).to_be_visible(timeout=20_000)
        assert page.get_by_role("button", name="Undo this action").count() == 0
        page.get_by_role("button", name="Trap sites", exact=True).click()
        _card(page, "Mangaroa Farm").get_by_role("button", name="Trial overview", exact=True).click()
        expect(page.get_by_text("Evidence waiting", exact=True)).to_be_visible(timeout=20_000)
        assert page.get_by_role("button", name="Undo this action").count() == 0


def test_undo_from_the_end_trial_result_screen_reopens_the_trial(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, END_SEED) as url:
        before = {n: _sheet(data_dir, n) for n in ("Trials", "Traps", "Windows", "Followups", "Visits", "Checks")}
        _to_end_trial_from_the_visit(page, url)
        _decide_unresolvable(page)
        expect(page.get_by_text("Marked unresolvable", exact=True)).to_be_visible(timeout=20_000)
        _decide_unresolvable(page)
        page.get_by_role("button", name="Continue to preview").click()
        expect(page.get_by_text("What ending does", exact=True)).to_be_visible(timeout=20_000)
        page.get_by_role("button", name="Confirm trial end").click()
        expect(page.get_by_text("Undo ends when you leave this screen or lock your phone.", exact=True)).to_be_visible(timeout=60_000)
        assert (_sheet(data_dir, "Trials")["Status"] == "Ended").all()
        page.get_by_role("button", name="Undo this action").click()
        expect(page.get_by_text("Everything this action changed has been put back.", exact=True)).to_be_visible(timeout=60_000)
        for name, frame in before.items():
            pd.testing.assert_frame_equal(_sheet(data_dir, name), frame, obj=f"{name} after undo")
