"""Drives the field navigation hot path with the speed probe on and records,
per tap, which SPEEDPROBE lines the server logged (FIELD_SPEED_PHASE1_BRIEF.md
Part B). Used by test_speed_navigation_runs.py for its assertions and runnable
directly to print a before/after report:

    .venv/bin/python tests/speed_nav_flow.py
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from test_speed_probe import ProbeApp, start_app, stop_app  # noqa: E402

SELECTOR_TEXT = "Select the trap you are standing at."


def _settle(page: Page) -> None:
    page.wait_for_timeout(1_200)


def _tap(page: Page, app: ProbeApp, steps: dict, name: str, action, destination) -> None:
    before = len(app.log_lines())
    action()
    expect(destination).to_be_visible(timeout=30_000)
    _settle(page)
    steps[name] = app.log_lines()[before:]


TRAP_SITES_HEADING = "Choose the trap site you are visiting today."


def _landing(page: Page):
    return (
        page.get_by_text("Resume checking?", exact=True)
        .or_(page.get_by_text(SELECTOR_TEXT, exact=True))
        .or_(page.get_by_text(TRAP_SITES_HEADING, exact=True))
        .or_(page.get_by_text("What did you find?", exact=True))
        .first
    )


def _where_landed(page: Page) -> str:
    if page.get_by_text("Resume checking?", exact=True).count():
        return "resume_prompt"
    if page.get_by_text("What did you find?", exact=True).count():
        return "check_form"
    if page.get_by_text(SELECTOR_TEXT, exact=True).count():
        return "visit_page"
    return "trap_sites"


def run_flow(page: Page, app: ProbeApp) -> dict:
    steps: dict[str, list[str]] = {}
    page.goto(app.url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    _settle(page)

    selector = page.get_by_text(SELECTOR_TEXT, exact=True)
    check_form = page.get_by_text("What did you find?", exact=True)
    check_buttons = page.get_by_role("button", name="Check", exact=True)

    _tap(page, app, steps, "start_checking",
         lambda: page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first.click(), selector)
    _tap(page, app, steps, "check_trap_1", lambda: check_buttons.nth(0).click(), check_form)
    _tap(page, app, steps, "back_to_selector",
         lambda: page.get_by_role("button", name="Back to trap selector", exact=False).click(), selector)
    _tap(page, app, steps, "check_another", lambda: check_buttons.nth(1).click(), check_form)

    # Reload on the check page: what does the app restore?
    page.reload(wait_until="domcontentloaded")
    _landing(page).wait_for(timeout=30_000)
    steps["_reload_on_check_page"] = _where_landed(page)
    if steps["_reload_on_check_page"] == "resume_prompt":
        page.get_by_role("button", name="Resume", exact=True).click()
        expect(check_form).to_be_visible(timeout=30_000)
    _settle(page)

    _tap(page, app, steps, "back_again",
         lambda: page.get_by_role("button", name="Back to trap selector", exact=False).click(), selector)

    # Reload on the visit (trap selector) page.
    page.reload(wait_until="domcontentloaded")
    _landing(page).wait_for(timeout=30_000)
    _settle(page)
    steps["_reload_on_visit_page"] = _where_landed(page)
    if steps["_reload_on_visit_page"] == "trap_sites":
        page.get_by_role("button", name=re.compile(r"^(Start|Resume) checking$", re.I)).first.click()
        expect(selector).to_be_visible(timeout=30_000)
        _settle(page)

    _tap(page, app, steps, "pause",
         lambda: page.get_by_role("button", name="Pause and return to Trap sites", exact=True).click(),
         page.get_by_role("button", name=re.compile(r"^Resume checking$", re.I)).first)

    _tap(page, app, steps, "resume_checking",
         lambda: page.get_by_role("button", name=re.compile(r"^Resume checking$", re.I)).first.click(), selector)
    _tap(page, app, steps, "check_before_exit", lambda: check_buttons.nth(0).click(), check_form)
    _tap(page, app, steps, "exit_to_trap_sites",
         lambda: page.get_by_role("button", name="Exit to Trap sites", exact=False).click(),
         page.get_by_role("button", name=re.compile(r"^Resume checking$", re.I)).first)

    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    steps["_reload_on_trap_sites"] = "trap_sites"
    return steps


def kinds(lines: list[str]) -> list[str]:
    return [re.search(r"kind=(\w+)", ln).group(1) for ln in lines]


if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp())
    process, log_file, app = start_app(tmp, {"SPEED_PROBE": "1"})
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            report = run_flow(page, app)
            browser.close()
    finally:
        stop_app(process, log_file)
    for name, value in report.items():
        if name.startswith("_"):
            print(f"{name}: {value}")
            continue
        print(f"--- {name}: {kinds(value)}")
        for line in value:
            print("   ", line)
