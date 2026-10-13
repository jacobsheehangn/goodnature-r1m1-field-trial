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


def pick_finding(page: Page, finding: str) -> None:
    page.get_by_role("radio", name=finding, exact=True).check(force=True)
    page.wait_for_timeout(900)


def pick(page: Page, group: str, option: str) -> None:
    """Choose an option in a named group: service, camera, carcass, or the group's own question text."""
    page.get_by_role("radiogroup", name=GROUPS.get(group, group)).get_by_role("radio", name=option, exact=True).check(force=True)
    page.wait_for_timeout(700)


def pick_species(page: Page, species: str, rat_type: str = "") -> None:
    page.get_by_role("radio", name=species, exact=True).check(force=True)
    page.wait_for_timeout(400)
    if rat_type:
        page.get_by_role("radio", name=rat_type, exact=True).check(force=True)
        page.wait_for_timeout(400)


def pick_condition(page: Page, condition: str) -> None:
    page.get_by_role("radio", name=condition, exact=True).check(force=True)
    page.wait_for_timeout(300)


def tick(page: Page, name: str | re.Pattern) -> None:
    page.get_by_role("checkbox", name=name).evaluate("el => el.click()")
    page.wait_for_timeout(300)


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
        if re.search(rf"{count} photos? saved", page.locator("body").inner_text()):
            break
        page.wait_for_timeout(250)
    page.wait_for_timeout(500)


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
