"""Answering the check form in a browser: the one place that knows how today's form is laid out.

Tests that drive the check page use these steps instead of their own role clicks, so a change to the form's layout changes this file
and not thirty others. Each step names what the operator does, not how the page draws it."""
from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import Page, expect

GROUPS = {"service": "Trap relured, reset and ready?", "camera": "Camera working and covering the trap?", "carcass": "Carcass collected?"}


def start_visit_and_open(page: Page, url: str, trap_id: str) -> None:
    """From the app's first screen to the check page of one trap (starts a visit)."""
    page.goto(url, wait_until="domcontentloaded")
    start = page.get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).first
    start.wait_for(timeout=45000)
    page.wait_for_timeout(1200)
    start.click()
    page.locator(f'[class*="visit_check_"][class*="_{trap_id}"] button').click()
    expect(page.get_by_text(trap_id).first).to_be_visible(timeout=20000)


def select(locator) -> None:
    """Choose a radio option. Playwright's check() reads the new state at once, but these controls update after the page's rerun, so in WebKit it
    can report "did not change its state" for a click that worked; so when it raises, wait for the rerun and look at the control itself, and only
    when it is still not selected use the keyboard (focus, then Space). (A second press on a selected segmented control would deselect it.)"""
    try:
        locator.check(force=True, timeout=6000)
        return
    except Exception:
        pass
    locator.page.wait_for_timeout(1500)
    if locator.get_attribute("aria-checked") == "true" or locator.is_checked():
        return
    locator.focus()
    locator.page.keyboard.press("Space")


def pick_finding(page: Page, finding: str) -> None:
    """Choose an outcome. When one is already chosen the six rows are not drawn: Change reopens them first."""
    row = page.get_by_role("radio", name=finding, exact=True)
    change = page.get_by_role("button", name="Change", exact=True)
    row.or_(change).first.wait_for(timeout=30000)
    if not row.count():
        page.get_by_role("button", name="Change", exact=True).click()
        page.wait_for_timeout(900)
    select(row)
    page.wait_for_timeout(900)


def pick(page: Page, group: str, option: str) -> None:
    """Choose an option in a named group: service, camera, carcass, or the group's own question text."""
    select(page.get_by_role("radiogroup", name=GROUPS.get(group, group)).get_by_role("radio", name=option, exact=True))
    page.wait_for_timeout(700)


def pick_species(page: Page, species: str, rat_type: str = "") -> None:
    select(page.get_by_role("radio", name=species, exact=True))
    page.wait_for_timeout(400)
    if rat_type:
        select(page.get_by_role("radio", name=rat_type, exact=True))
        page.wait_for_timeout(400)


def pick_condition(page: Page, condition: str) -> None:
    select(page.get_by_role("radio", name=condition, exact=True))
    page.wait_for_timeout(300)


def tick(page: Page, name: str | re.Pattern) -> None:
    page.get_by_role("checkbox", name=name).evaluate("el => el.click()")
    page.wait_for_timeout(300)


def add_note(page: Page, text: str) -> None:
    """Open "Anything else to record?" and type a note."""
    if not page.get_by_label("Notes").is_visible():
        page.get_by_text("Anything else to record?").click()
        page.wait_for_timeout(400)
    type_into(page, "Notes", text)


def notes_box(page: Page):
    """The notes field, opening "Anything else to record?" first when it is closed (it is open when it already holds a note)."""
    box = page.get_by_label("Notes")
    if not box.is_visible():
        page.get_by_text("Anything else to record?").click()
        page.wait_for_timeout(400)
    return box


def answer_still_set(page: Page) -> None:
    """Trap still set, no animal, with the service and (when the trap has one) the camera answered Yes."""
    pick_finding(page, "Trap still set, no animal")
    pick(page, "service", "Yes")
    if page.get_by_role("radiogroup", name=GROUPS["camera"]).count():
        pick(page, "camera", "Yes")


def set_check_time(page: Page, on: bool = True) -> None:
    switch = page.get_by_role("switch", name="Change check time")
    if switch.is_checked() != on:
        switch.evaluate("el => el.click()")
        page.wait_for_timeout(600)


def type_into(page: Page, label: str, text: str) -> None:
    box = page.get_by_label(label)
    box.fill(text)
    box.press("Tab")
    page.wait_for_timeout(600)


def uploader(page: Page):
    return page.frame_locator('iframe[title="app.r1m1_photo_upload"]')


def uploader_text(page: Page) -> str:
    try:
        return " | ".join(x.strip() for x in uploader(page).locator(".status, .summary, button.retry").all_inner_texts() if x.strip())[:140]
    except Exception as exc:
        return f"(uploader not on screen: {type(exc).__name__})"


def stage_photos(page: Page, folder: Path, count: int) -> None:
    """Choose `count` photos in the uploader and wait until they all show as saved."""
    from PIL import Image
    paths = []
    for i in range(count):
        path = Path(folder) / f"field_photo_{i}.jpg"
        Image.new("RGB", (640, 480), (60 + i * 40, 100, 140)).save(path)
        paths.append(str(path))
    uploader(page).locator('input[type="file"]').wait_for(state="attached", timeout=30000)
    uploader(page).locator('input[type="file"]').set_input_files(paths)
    for _ in range(80):
        if re.search(rf"{count} photos? saved", uploader_text(page)):
            break
        page.wait_for_timeout(250)
    page.wait_for_timeout(500)


def wait_photos_saved(page: Page, count: int, timeout_s: int = 30) -> None:
    """Wait until the uploader says `count` photos are saved (the line lives in the uploader's own frame, not in the page text)."""
    for _ in range(timeout_s * 4):
        if re.search(rf"{count} photos? saved", uploader_text(page)):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the uploader never showed {count} photos saved: {uploader_text(page)!r}")


def save_check(page: Page, wait_ms: int = 9000) -> None:
    page.get_by_role("button", name=re.compile(r"^Save check$")).click()
    page.wait_for_timeout(wait_ms)


def body_lines(page: Page, *needles: str) -> list:
    body = page.locator("body").inner_text()
    return [line.strip() for line in body.splitlines() if any(n.lower() in line.lower() for n in needles)][:8]


# What is on disk
def pending_files(data_dir: Path) -> list:
    root = Path(data_dir) / ".pending_photos"
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) if root.exists() else []


def photo_events(data_dir: Path, event: str) -> list:
    log = Path(data_dir) / "photo_upload_log.jsonl"
    if not log.exists():
        return []
    return [rec for rec in (json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()) if rec.get("event") == event]
