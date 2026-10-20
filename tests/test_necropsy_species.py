"""Phase 4 (TRIAL_LIFECYCLE_BRIEF.md): necropsy species confirmation, the Camera review (video) row, the
form rebuilt with visible controls and one submit, the Trial Performance coverage figure, the correction
form's field-recorded context, and defects D1-D4."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import check_form as cf
from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from necropsy_seed import NECROPSY_SEED  # noqa: E402
from test_trial_model_ui import _serve, _sheet  # noqa: E402
from test_trial_screens import _choose, _home  # noqa: E402

MOUSE_RANGES = ["0–10 g", "11–20 g", "21–30 g", "31+ g"]
RAT_RANGES = ["0–50 g", "51–100 g", "101–150 g", "151–200 g", "201–250 g", "251–300 g", "301–350 g", "351–400 g", "400+ g"]
# The same data plus an open camera review (for D4), on a different window.
WITH_OPEN_CAMERA_REVIEW = NECROPSY_SEED + """
    data = app.load_data()
    app.add_followup(data, "Camera review", "MAN", trap_id, "V0", "W-K1", "MAN-011", "Dead animal found", "d", "Normal")
    app.save_data(data)
"""


def _open_task(page: Page, url: str, task_type: str) -> None:
    _home(page, url)
    page.get_by_role("link", name="Follow-ups").click()
    expect(page.get_by_role("heading", name="Follow-ups", exact=True)).to_be_visible(timeout=30_000)
    card = page.get_by_text(task_type, exact=True).first.locator("xpath=ancestor::div[.//button][1]")
    card.get_by_role("button", name="Review", exact=True).click()
    expect(page.get_by_role("heading", name=task_type)).to_be_visible(timeout=30_000) if task_type != "Necropsy review" else expect(page.get_by_text("Species", exact=True)).to_be_visible(timeout=30_000)


def _chips(page: Page) -> list:
    return page.locator('[class*="st-key-chips_nec_weight"] button[role="radio"]').all_inner_texts()


def _fill_the_form(page: Page, *, weight: str, status: str = "Complete", assessment: str = "Supports humane kill", final: str = "Yes") -> None:
    page.get_by_text(status, exact=True).first.click()
    page.get_by_text(assessment, exact=True).first.click()
    page.locator('[class*="st-key-chips_nec_weight"] button[role="radio"]').filter(has_text=re.compile(rf"^{re.escape(weight)}$")).click()
    page.locator('[class*="st-key-rows2_nec_final"]').get_by_text(final, exact=True).click()


def test_a_mouse_guess_corrected_to_a_rat_switches_the_weight_scale_and_keeps_the_original_guess(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, NECROPSY_SEED) as url:
        _open_task(page, url, "Necropsy review")
        # The person entering the result can see what the footage showed; the value-test rows are gone.
        context = page.locator(".st-key-card_nec_context").inner_text()
        assert "Camera review (video)" in context and "Humane" in context
        assert all(label not in context for label in ("Build", "Reason", "Camera\n")), context
        # Pre-filled with the field guess, which is shown; the weight scale is the mouse scale.
        expect(page.get_by_text("Field-recorded guess: Mouse", exact=True)).to_be_visible()
        assert page.locator('[class*="st-key-species_nec"] [data-testid="stRadioOption"]:has(input:checked)').inner_text().strip() == "Mouse"
        assert _chips(page) == MOUSE_RANGES
        page.locator('[class*="st-key-chips_nec_weight"] button[role="radio"]').filter(has_text="11–20 g").click()
        page.wait_for_timeout(600)
        # Changing the species mid-form switches the options at once and clears the old selection.
        page.locator('[class*="st-key-species_nec"]').get_by_text("Rat", exact=True).click()
        expect(page.locator('[class*="st-key-chips_nec_weight"] button[role="radio"]').nth(8)).to_be_visible(timeout=15_000)
        assert _chips(page) == RAT_RANGES
        assert page.locator('[class*="st-key-chips_nec_weight"] button[aria-checked="true"]').count() == 0, "a weight chosen for the old species is cleared"
        # Rat type appears for a rat and is required.
        page.locator('[class*="st-key-seg_rat_nec"] button[role="radio"]').filter(has_text="Norway rat").click()
        page.wait_for_timeout(600)
        _fill_the_form(page, weight="201–250 g")
        assert page.get_by_label("Reason", exact=False).count() == 0 and page.get_by_text("Correction reason", exact=False).count() == 0, "no typed reason"
        page.get_by_role("button", name="Save necropsy review").click()
        expect(page.get_by_text("Necropsy review saved", exact=True)).to_be_visible(timeout=60_000)

        w = _sheet(data_dir, "Windows").set_index("Window ID").loc["W-NEC"]
        assert w["Species"] == "Rat" and w["Rat Type"] == "Norway rat" and w["Species Confirmed"] == "Yes"
        assert w["Field-Recorded Species"] == "Mouse", "the original guess is still readable"
        assert w["Animal Weight Range"] == "201–250 g" and w["Final Humane Kill"] == "Yes" and w["Necropsy Status"] == "Complete"
        audit = _sheet(data_dir, "Audit Log")
        mine = audit[(audit["Record ID"] == "W-NEC") & (audit["Field"].isin(["Species", "Rat Type"]))].set_index("Field")
        assert mine.loc["Species", ["Previous Value", "New Value", "Reason"]].tolist() == ["Mouse", "Rat", "Corrected at necropsy"]
        assert mine.loc["Rat Type", "New Value"] == "Norway rat"
        fu = _sheet(data_dir, "Followups")
        assert fu[fu["Follow-up Type"] == "Necropsy review"].iloc[0]["Status"] == "Complete"


def test_confirming_the_field_guess_needs_no_reason_and_is_still_logged(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, NECROPSY_SEED) as url:
        _open_task(page, url, "Necropsy review")
        _fill_the_form(page, weight="11–20 g", final="No", assessment="Does not support humane kill")
        page.get_by_role("button", name="Save necropsy review").click()
        expect(page.get_by_text("Necropsy review saved", exact=True)).to_be_visible(timeout=60_000)
        w = _sheet(data_dir, "Windows").set_index("Window ID").loc["W-NEC"]
        assert w["Species"] == "Mouse" and w["Field-Recorded Species"] == "Mouse" and w["Species Confirmed"] == "Yes"
        audit = _sheet(data_dir, "Audit Log")
        entry = audit[(audit["Record ID"] == "W-NEC") & (audit["Field"] == "Species")].iloc[0]
        assert [entry["Previous Value"], entry["New Value"], entry["Reason"]] == ["Mouse", "Mouse", "Confirmed at necropsy"]


def test_the_form_refuses_an_incomplete_save_and_a_rat_without_a_rat_type(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, NECROPSY_SEED) as url:
        before = _sheet(data_dir, "Windows")
        _open_task(page, url, "Necropsy review")
        page.get_by_role("button", name="Save necropsy review").click()
        expect(page.get_by_text("Complete every necropsy field, including the weight range.", exact=True)).to_be_visible(timeout=30_000)
        page.locator('[class*="st-key-species_nec"]').get_by_text("Rat", exact=True).click()
        page.wait_for_timeout(800)
        _fill_the_form(page, weight="151–200 g")
        page.get_by_role("button", name="Save necropsy review").click()
        expect(page.get_by_text("Choose the rat type.", exact=True)).to_be_visible(timeout=30_000)
        import pandas as pd
        pd.testing.assert_frame_equal(_sheet(data_dir, "Windows"), before)


def test_task_pages_have_one_h1_the_right_copy_and_no_misplaced_caption(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, WITH_OPEN_CAMERA_REVIEW) as url:
        # D2 on the list page: it keeps its own H1; on a task page the task title is the only H1.
        _home(page, url)
        page.get_by_role("link", name="Follow-ups").click()
        expect(page.get_by_role("heading", name="Follow-ups", exact=True)).to_be_visible(timeout=30_000)
        assert page.locator('h1,[role="heading"][aria-level="1"]').all_inner_texts() == ["Follow-ups"]  # Phase 7b: the list's title is a level-1 heading by role
        # Necropsy: D2, D3, D4, and the trimmed context.
        card = page.get_by_text("Necropsy review", exact=True).first.locator("xpath=ancestor::div[.//button][1]")
        card.get_by_role("button", name="Review", exact=True).click()
        expect(page.get_by_text("Species", exact=True)).to_be_visible(timeout=30_000)
        assert page.locator('h1,[role="heading"][aria-level="1"]').all_inner_texts() == ["Necropsy review"]
        expect(page.get_by_text("Attach photos of the animal. You can choose several.", exact=True)).to_be_visible()
        expect(page.get_by_text("Saving this updates the kill result, the humane-kill figures, the review status and the photos.", exact=True)).to_be_visible()
        for jargon in ("KPI", "test-window", "Same upload behaviour as trap-check photos", "Record when events occurred in the footage"):
            assert page.get_by_text(jargon, exact=False).count() == 0, jargon
        page.get_by_role("button", name="Back to task list").click()
        expect(page.get_by_role("heading", name="Follow-ups", exact=True)).to_be_visible(timeout=30_000)
        # Camera review: one H1, the footage caption belongs here, Build / Camera / Reason rows are gone.
        card = page.get_by_text("Camera review", exact=True).first.locator("xpath=ancestor::div[.//button][1]")
        card.get_by_role("button", name="Review", exact=True).click()
        expect(page.get_by_role("heading", name="Camera review", exact=True)).to_be_visible(timeout=30_000)
        assert page.locator('h1,[role="heading"][aria-level="1"]').all_inner_texts() == ["Camera review"]
        expect(page.get_by_text("Record when things happened in the footage, not when you watched it.", exact=True)).to_be_visible()
        context = page.locator('[class*="st-key-card_task_context"]').inner_text()
        for kept in ("Trap", "Site", "Bag ID"):
            assert kept in context
        for dropped in ("Build:", "Camera:", "Reason:"):
            assert dropped not in context


def test_the_first_part_of_the_necropsy_page_has_no_blank_strip_under_the_uploader(page: Page, tmp_path: Path) -> None:
    """D1: about 186px of empty space separated the Photos card from the next field."""
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, NECROPSY_SEED) as url:
        _open_task(page, url, "Necropsy review")
        page.wait_for_timeout(1200)
        gap = page.evaluate("""() => { const frame = [...document.querySelectorAll('iframe')].find(f => f.getBoundingClientRect().height > 50); const species = [...document.querySelectorAll('label')].find(l => l.innerText.trim() === 'Necropsy status');
          const card = frame.getBoundingClientRect(); const next = species.getBoundingClientRect(); return {frame_h: Math.round(card.height), gap: Math.round(next.top - card.bottom)}; }""")
        assert gap["frame_h"] <= 140, f"the uploader frame is sized to its content: {gap}"
        assert gap["gap"] <= 60, f"nothing blank between the uploader and the next question: {gap}"


def test_species_comes_before_photos_and_is_fully_on_the_first_phone_screen(page: Page, tmp_path: Path) -> None:
    """QA brief Q5: species is the first decision, so it sits above Photos and its tiles (labels included) fit 390x844."""
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, NECROPSY_SEED) as url:
        _open_task(page, url, "Necropsy review")
        page.wait_for_timeout(1200)
        box = page.evaluate("""() => { const tiles = document.querySelector('[class*="st-key-species_nec"]').getBoundingClientRect(); const photos = [...document.querySelectorAll('.r1-label')].find(e => e.innerText.trim() === 'Photos').getBoundingClientRect();
          return {tiles_bottom: Math.round(tiles.bottom), tiles_top: Math.round(tiles.top), photos_top: Math.round(photos.top)}; }""")
        assert box["tiles_top"] < box["photos_top"], f"species above photos: {box}"
        assert box["tiles_bottom"] <= 844, f"the species tiles, labels included, fit the first phone screen: {box}"


def test_trial_performance_shows_confirmed_coverage_on_rat_type_and_rodent_weight(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, NECROPSY_SEED) as url:
        _home(page, url)
        page.get_by_role("link", name="Trial performance").click()
        expect(page.get_by_text("Trap type", exact=True)).to_be_visible(timeout=30_000)
        page.wait_for_timeout(1000)
        _choose(page, "Trap type", "R1")
        caption = "4 of 7 windows have necropsy-confirmed species. Remaining 3 rest on unconfirmed field guesses."
        # Rodent weight is the default breakdown; Rat type carries the same figure; Build does not.
        expect(page.get_by_text(caption, exact=True)).to_be_visible(timeout=30_000)
        _choose(page, "Break down performance by", "Rat type")
        expect(page.get_by_text(caption, exact=True)).to_be_visible(timeout=30_000)
        _choose(page, "Break down performance by", "Build")
        expect(page.get_by_text("have necropsy-confirmed species", exact=False)).to_have_count(0, timeout=15_000)


def test_the_correction_form_shows_the_preserved_field_guess_beside_the_confirmed_value(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    seed = NECROPSY_SEED + """
    data = app.load_data()
    i = data["Windows"].index[data["Windows"]["Window ID"] == "W-K1"][0]
    data["Windows"].loc[i, ["Species", "Field-Recorded Species", "Species Confirmed"]] = ["Rat", "Mouse", "Yes"]
    app.save_data(data)
    """
    with _serve(data_dir, seed) as url:
        _home(page, url)
        page.get_by_role("button", name="Administration").click()
        page.get_by_role("link", name="Data & records", exact=True).click()
        expect(page.get_by_text("Record type", exact=True)).to_be_visible(timeout=30_000)
        page.wait_for_timeout(800)
        _choose(page, "Record type", "Necropsy evidence")
        page.wait_for_timeout(800)
        combo = page.get_by_role("combobox", name=re.compile("Select closed test window"))
        target = page.get_by_role("option").filter(has_text="W-K1").first
        for _ in range(4):
            combo.click()
            try:
                target.wait_for(state="visible", timeout=3_000)
                break
            except Exception:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
        target.click()
        expect(page.get_by_text("Field-recorded: Mouse · confirmed at necropsy", exact=True)).to_be_visible(timeout=30_000)


def test_the_check_forms_uploader_keeps_its_original_sizing(page: Page, tmp_path: Path) -> None:
    """QA brief Q1: the uploader sizing change is scoped to the necropsy pages. The check form's frame must keep the
    original 150px floor (it measures the same on origin/main), so the field-critical path is untouched."""
    from test_trial_model_ui import _SEED_TRIALS_EVERYWHERE  # noqa: PLC0415
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size({"width": 390, "height": 844})
    with _serve(data_dir, _SEED_TRIALS_EVERYWHERE) as url:
        _home(page, url)
        page.get_by_role("button", name="Start checking").first.click()
        expect(page.get_by_role("button", name="Finish site check")).to_be_visible(timeout=30_000)
        page.get_by_role("button", name="Check", exact=True).nth(2).click()
        expect(page.get_by_text("All as expected?", exact=True)).to_be_visible(timeout=20_000)
        cf.pick_finding(page, "Dead animal found")
        expect(page.get_by_text("Carcass collected?", exact=False)).to_be_visible(timeout=20_000)
        cf.pick(page, "carcass", "Yes")  # a collected carcass is photographed
        page.wait_for_function("() => [...document.querySelectorAll('iframe')].some(f => f.getBoundingClientRect().height > 50)", timeout=20_000)
        page.wait_for_timeout(1500)
        height = page.evaluate("() => Math.round([...document.querySelectorAll('iframe')].map(f => f.getBoundingClientRect().height).filter(h => h > 0).sort((a, b) => b - a)[0])")
        print("CHECK_FORM_UPLOADER_FRAME_HEIGHT", height)
        assert height >= 150, f"the check form's uploader frame must keep the original 150px floor, got {height}"
