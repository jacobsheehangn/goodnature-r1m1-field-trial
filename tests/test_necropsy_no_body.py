"""Closing a necropsy task for a kill whose body was not recovered (owner, 11 Nov 2026).

On the live app eight necropsy tasks were inhumane kills, many with no body. The form could not close them: it asked for a weight range (nothing to weigh), it refused
"Unable to assess" with a definite final result, and after refusing it left the Save button disabled on "Saving…" for good. Now: the weight range is needed only when the
necropsy is Complete; a NOT-humane result (No) can be recorded without a completed necropsy, a humane one (Yes) cannot; the audit log says a result was set without one; and a
refused Save gives the button back."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from necropsy_seed import NECROPSY_SEED  # noqa: E402
from test_necropsy_species import _open_task  # noqa: E402
from test_trial_model_ui import _serve, _sheet  # noqa: E402

SAVE = "Save necropsy review"


def _answer(page: Page, *, status: str, assessment: str, final: str, weight: str = "") -> None:
    """The form's own controls, without a weight unless one is given."""
    page.get_by_text(status, exact=True).first.click()
    page.get_by_text(assessment, exact=True).first.click()
    if weight:
        page.locator('[class*="st-key-chips_nec_weight"] button[role="radio"]').filter(has_text=weight).click()
    page.locator('[class*="st-key-rows2_nec_final"]').get_by_text(final, exact=True).click()


def test_a_refused_save_gives_the_button_back_instead_of_staying_on_saving(page: Page, tmp_path: Path) -> None:
    """Touching only the form's own fields never redraws the page, so the button used to stay disabled on "Saving…" after a refusal."""
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, NECROPSY_SEED) as url:
        before = _sheet(data_dir, "Windows")
        _open_task(page, url, "Necropsy review")
        page.get_by_role("button", name=SAVE).click()
        expect(page.get_by_text("Complete every necropsy field, including the weight range.", exact=True)).to_be_visible(timeout=30_000)
        expect(page.get_by_role("button", name=SAVE)).to_be_enabled(timeout=15_000)  # not "Saving…", and tappable again
        assert page.get_by_role("button", name="Saving…").count() == 0
        pd.testing.assert_frame_equal(_sheet(data_dir, "Windows"), before)


@pytest.mark.parametrize("assessment", ["Does not support humane kill", "Not assessable"])
def test_a_kill_with_no_body_closes_as_not_humane_without_a_weight(assessment: str, page: Page, tmp_path: Path) -> None:
    """The owner's case: Unable to assess, and a final result of No, with no weight range."""
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, NECROPSY_SEED) as url:
        _open_task(page, url, "Necropsy review")
        _answer(page, status="Unable to assess", assessment=assessment, final="No")
        page.get_by_role("button", name=SAVE).click()
        expect(page.get_by_text("Necropsy review saved", exact=True)).to_be_visible(timeout=60_000)
        window = _sheet(data_dir, "Windows").set_index("Window ID").loc["W-NEC"]
        assert [window["Necropsy Status"], window["Necropsy Assessment"], window["Final Humane Kill"], window["Animal Weight Range"]] == ["Unable to assess", assessment, "No", ""]
        task = _sheet(data_dir, "Followups")
        assert task[(task["Follow-up Type"] == "Necropsy review") & (task["Window ID"] == "W-NEC")].iloc[0]["Status"] == "Complete"
        audit = _sheet(data_dir, "Audit Log")
        entry = audit[(audit["Record ID"] == "W-NEC") & (audit["Field"] == "Final Humane Kill")].iloc[0]
        assert [entry["Previous Value"], entry["New Value"]] == ["Pending", "No"]
        assert entry["Reason"] == "Recorded without a completed necropsy (necropsy status: Unable to assess)"


def test_no_body_and_a_humane_result_is_refused_and_nothing_is_written(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, NECROPSY_SEED) as url:
        before = {name: _sheet(data_dir, name) for name in ("Windows", "Followups", "Audit Log")}
        _open_task(page, url, "Necropsy review")
        _answer(page, status="Unable to assess", assessment="Not assessable", final="Yes")
        page.get_by_role("button", name=SAVE).click()
        expect(page.get_by_text("A humane result needs a completed necropsy. Without one, record No if it was not humane, or Unclear or Not assessable.", exact=True)).to_be_visible(timeout=30_000)
        expect(page.get_by_role("button", name=SAVE)).to_be_enabled(timeout=15_000)
        for name, frame in before.items():
            pd.testing.assert_frame_equal(_sheet(data_dir, name), frame)


def test_a_completed_necropsy_still_needs_its_weight_range(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, NECROPSY_SEED) as url:
        before = _sheet(data_dir, "Windows")
        _open_task(page, url, "Necropsy review")
        _answer(page, status="Complete", assessment="Supports humane kill", final="Yes")
        page.get_by_role("button", name=SAVE).click()
        expect(page.get_by_text("Complete every necropsy field, including the weight range.", exact=True)).to_be_visible(timeout=30_000)
        expect(page.get_by_role("button", name=SAVE)).to_be_enabled(timeout=15_000)
        pd.testing.assert_frame_equal(_sheet(data_dir, "Windows"), before)


# ---- the outcome target: no real-world outcome is unreachable ------------------------------------------------------------------------------------------------
from test_correction_consistency import _run  # noqa: E402

REAL_WORLD_OUTCOMES = {
    "a completed necropsy: humane": ("Complete", "Supports humane kill", "Yes"),
    "a completed necropsy: not humane": ("Complete", "Does not support humane kill", "No"),
    "a completed necropsy: unclear": ("Complete", "Unclear", "Unclear"),
    "no body: not humane from the video or field notes": ("Unable to assess", "Not assessable", "No"),
    "no body: not humane, assessment recorded as not supporting a humane kill": ("Unable to assess", "Does not support humane kill", "No"),
    "no body: cannot tell": ("Unable to assess", "Not assessable", "Not assessable"),
    "necropsy not completed: not humane": ("Not completed", "Not assessable", "No"),
    "necropsy not completed: cannot tell": ("Not completed", "Unclear", "Unclear"),
}


def test_every_real_world_necropsy_outcome_can_be_recorded_and_the_refusals_name_the_way_out(tmp_path: Path) -> None:
    """The rules may refuse a combination; they may never leave an outcome the operator really has with nowhere to go (owner, 11 Nov: no system block on expected outcomes)."""
    out = _run(
        tmp_path,
        """
        import json, itertools, app
        statuses = ["Complete", "Not completed", "Unable to assess"]
        assessments = ["Supports humane kill", "Does not support humane kill", "Unclear", "Not assessable"]
        finals = ["Yes", "No", "Unclear", "Not assessable"]
        valid = {s + "|" + f: any(not app.necropsy_consistency_errors(s, a, f) for a in assessments) for s in statuses for f in finals}
        refusals = sorted({e for s, a, f in itertools.product(statuses, assessments, finals) for e in app.necropsy_consistency_errors(s, a, f)})
        outcomes = %s
        print(json.dumps({"valid": valid, "refusals": refusals, "outcomes": {k: app.necropsy_consistency_errors(*v) for k, v in outcomes.items()}}))
        """ % repr({k: list(v) for k, v in REAL_WORLD_OUTCOMES.items()}),
    )
    for name, errors in out["outcomes"].items():
        assert errors == [], f"{name} cannot be recorded: {errors}"
    # every final result can be recorded under every status, except a HUMANE one without a completed necropsy (that is the rule, and its refusal says what to record instead)
    dead = sorted(key for key, ok in out["valid"].items() if not ok)
    assert dead == ["Not completed|Yes", "Unable to assess|Yes"], dead
    humane_refusal = [r for r in out["refusals"] if "humane result needs a completed necropsy" in r]
    assert humane_refusal and "record No" in humane_refusal[0], out["refusals"]
