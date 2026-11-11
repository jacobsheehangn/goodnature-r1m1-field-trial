"""No system block on an expected outcome: a refusal or a failure never leaves the operator with a disabled, busy button (11 Nov 2026).

The defect: a button that is drawn busy ("Saving…") on the run that does the work, then shows a refusal in place (or st.stop()s) and does nothing further, stays on the screen
disabled until something else reruns the page; inside a form nothing does. Eight necropsy tasks could not be closed. The rule, from `refuse()` in app.py: a refusal or a failure ends
the run with a redraw that keeps the reason (refuse(...), or the reason in session state and st.rerun()).

Three kinds of guard. (1) A lint over app.py: every armed-button block, and the shared save pipeline, obeys the rule. (2) Browser tests: a refused or failed save gives the button back
on the forms that use a form's own submit button or the shared pipeline. (3) The necropsy review's own tests (tests/test_necropsy_no_body.py)."""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).resolve().parent))
from necropsy_seed import NECROPSY_SEED  # noqa: E402
from test_necropsy_species import _open_task  # noqa: E402
from test_trial_model_ui import _sheet  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ARMED_CALLS = {"two_phase_button", "_action_buttons"}
REDRAWS = {"rerun", "refuse", "_correction_flash", "go", "finish", "fail", "set_page"}  # each ends the run (st.rerun raises) or navigates


def _name(call: ast.Call) -> str:
    return call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")


def _is_error_render(node: ast.AST) -> bool:
    """A statement that draws an error panel in place."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    text = ast.unparse(node.value)
    return bool(re.search(r"message_(html|panel)\(\s*[\"']error[\"']", text))


def _ends_the_run(node: ast.AST) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and _name(node.value) in REDRAWS


def _armed_names(scope: ast.AST) -> set:
    names = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and _name(node.value) in ARMED_CALLS:
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def _blocks(node: ast.AST):
    """Every statement list inside a node."""
    for field in ("body", "orelse", "finalbody"):
        stmts = getattr(node, field, None)
        if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.stmt):
            yield stmts
    for handler in getattr(node, "handlers", []):
        yield handler.body


def _violations_in_block(stmts: list, where: str) -> list:
    found = []
    for i, stmt in enumerate(stmts):
        if _is_error_render(stmt) and not any(_ends_the_run(later) for later in stmts[i + 1:]):
            found.append(f"{where}:{stmt.lineno}: an error is drawn in place and the run carries on (use refuse(...), or keep the reason and st.rerun())")
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and ast.unparse(stmt.value.func) == "st.stop":
            found.append(f"{where}:{stmt.lineno}: st.stop() in an armed block leaves the busy button on the screen (use refuse(...))")
        for inner in _blocks(stmt):
            found += _violations_in_block(inner, where)
    return found


def armed_button_violations(source: str, filename: str = "app.py") -> list:
    tree = ast.parse(source)
    found = []
    scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for scope in scopes:
        names = _armed_names(scope)
        for node in ast.walk(scope):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            direct = any(isinstance(n, ast.Call) and _name(n) in ARMED_CALLS for n in ast.walk(test))
            named = any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(test))
            if direct or named:
                found += _violations_in_block(node.body, filename)
    found = sorted(set(found))
    # the shared save pipeline: a failed save must not st.stop() either
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "commit_staged_records_with_photos"):
        for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n.func) == "st.stop"):
            found.append(f"{filename}:{call.lineno}: st.stop() in commit_staged_records_with_photos (a failed save must use refuse(...))")
    return found


def test_the_lint_catches_the_defect_it_exists_for() -> None:
    bad = '''
def page():
    clicked = two_phase_button("Save", "k", "Saving…")
    if clicked:
        try:
            do()
        except ValueError as exc:
            st.markdown(design.message_html("error", "Nothing was changed", str(exc)), unsafe_allow_html=True)
'''
    good = bad.replace('st.markdown(design.message_html("error", "Nothing was changed", str(exc)), unsafe_allow_html=True)', 'refuse("Nothing was changed", [str(exc)])')
    stopped = bad.replace('st.markdown(design.message_html("error", "Nothing was changed", str(exc)), unsafe_allow_html=True)', "st.stop()")
    assert len(armed_button_violations(bad)) == 1 and len(armed_button_violations(stopped)) == 1
    assert armed_button_violations(good) == []


def test_no_armed_button_shows_a_refusal_in_place_or_stops() -> None:
    assert armed_button_violations((ROOT / "app.py").read_text(encoding="utf-8")) == []


# ---- the browser: a refused or failed save gives the button back -------------------------------------------------------------------------------------------
from contextlib import contextmanager  # noqa: E402
from test_button_loading_feedback_tier2 import suspect_r1_window_app  # noqa: E402,F401  (the fixture: one R1 trap whose earliest window starts after it was deployed)


@contextmanager
def forced_commit_failure():
    """Every commit fails (R1M1_TEST_FAIL_COMMIT, test only), for a server started inside the block."""
    previous = os.environ.get("R1M1_TEST_FAIL_COMMIT")
    os.environ["R1M1_TEST_FAIL_COMMIT"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("R1M1_TEST_FAIL_COMMIT", None)
        else:
            os.environ["R1M1_TEST_FAIL_COMMIT"] = previous


def test_a_failed_necropsy_save_says_so_and_gives_the_button_back(page: Page, tmp_path: Path) -> None:
    from test_trial_model_ui import _serve
    import pandas as pd
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with forced_commit_failure(), _serve(data_dir, NECROPSY_SEED) as url:
        before = _sheet(data_dir, "Windows")
        _open_task(page, url, "Necropsy review")
        page.get_by_text("Complete", exact=True).first.click()
        page.get_by_text("Supports humane kill", exact=True).first.click()
        page.locator('[class*="st-key-chips_nec_weight"] button[role="radio"]').filter(has_text="11–20 g").click()
        page.locator('[class*="st-key-rows2_nec_final"]').get_by_text("Yes", exact=True).click()
        page.get_by_role("button", name="Save necropsy review").click()
        expect(page.get_by_text("Save failed", exact=True)).to_be_visible(timeout=60_000)
        expect(page.get_by_role("button", name="Save necropsy review")).to_be_enabled(timeout=15_000)  # not "Saving…", not disabled
        assert page.get_by_role("button", name="Saving…").count() == 0
        pd.testing.assert_frame_equal(_sheet(data_dir, "Windows"), before)  # and nothing was written


def test_a_failed_check_save_says_so_and_gives_the_button_back(page: Page, tmp_path: Path) -> None:
    """The same shared pipeline, from the check form: "Save failed", and Save check is Save check again."""
    import re
    import check_save_matrix as m
    import test_check_save_golden_ui as g
    cell = dict(profile="camera_trial", finding="Trap still set, no animal", service="Yes", camera="Yes", notes="")
    trap_id = m.PROFILES[cell["profile"]]["trap"]
    page.set_viewport_size({"width": 414, "height": 896})
    data_dir = tmp_path / "data"; data_dir.mkdir()
    with forced_commit_failure(), g._serve(data_dir) as url:
        page.goto(url, wait_until="domcontentloaded")
        start = page.get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).first
        start.wait_for(timeout=45000)
        page.wait_for_timeout(1200)
        start.click()
        page.locator(f'[class*="visit_check_"][class*="_{trap_id}"] button').click()
        expect(page.get_by_text(trap_id).first).to_be_visible(timeout=20000)
        g._answer_the_form(page, cell)
        page.get_by_role("button", name=re.compile(r"^Save check$")).click()
        expect(page.get_by_text("Save failed", exact=True)).to_be_visible(timeout=40000)
        expect(page.get_by_role("button", name=re.compile(r"^Save check$"))).to_be_enabled(timeout=15000)
        assert page.get_by_role("button", name=re.compile(r"Saving check")).count() == 0


def test_an_empty_true_deployment_date_is_refused_and_apply_comes_back(page: Page, suspect_r1_window_app) -> None:
    """A refusal that is not a missing field: the date cleared. It used to be drawn in place, leaving "Applying…" on the button."""
    import test_admin_data as t
    import admin_page as ap
    url, data_dir, seeded = suspect_r1_window_app
    page.set_viewport_size(t.DESKTOP)
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    ap.open_data_page(page, "Window start corrections")
    card = page.locator(f'[class*="st-key-card_winfix_{seeded["trap_id"]}"]')
    expect(card).to_be_visible(timeout=15_000)
    card.locator('[data-testid="stDateInput"] input').first.fill("")
    page.keyboard.press("Tab")
    page.get_by_role("textbox", name="Reason", exact=True).fill("Starts were stamped at sign-up, not deployment.")
    page.locator('[role="heading"][aria-level="1"]').first.click()
    page.wait_for_timeout(1_500)
    card.get_by_role("button", name="Apply this trap", exact=True).click()
    expect(page.get_by_text("Enter the true deployment date and time.", exact=True)).to_be_visible(timeout=30_000)
    expect(card.get_by_role("button", name="Apply this trap", exact=True)).to_be_enabled(timeout=15_000)  # not "Applying…"
    windows = _sheet(data_dir, "Windows")
    assert windows[windows["Window ID"] == seeded["window_id"]].iloc[0]["Start Time"].startswith("2026-08-05 09:00")  # nothing was written
