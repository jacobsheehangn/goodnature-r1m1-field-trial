"""Driving the administration pages in a browser: the one place that knows how they are reached and laid out (a change to the navigation or to Trial setup
changes this file, not a dozen tests)."""
from __future__ import annotations

import re

from playwright.sync_api import Page, expect

import check_form as cf


def open_trial_setup(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    go_to(page, "Trial setup")


def go_to(page: Page, item: str) -> None:
    """An Administration item, through the menu a phone calls More and a desktop calls Administration."""
    width = page.viewport_size["width"]
    name = re.compile(rf"^{re.escape(item)}\s*\d*$")  # Follow-ups and Data quality carry a count after their name
    if width <= 700:
        page.get_by_role("button", name="More", exact=True).click()
        page.get_by_role("dialog", name="More").get_by_role("link", name=name).click()
    else:
        page.get_by_role("button", name="Administration", exact=False).click()
        page.get_by_role("link", name=name).click()
    page.wait_for_timeout(1500)


def open_trap(page: Page, url: str, trap_id: str) -> None:
    """From the first screen to one trap's page (Trial setup, then the trap's Edit)."""
    open_trial_setup(page, url)
    page.locator(f".st-key-setup_edit_trap_{trap_id} button").click()
    expect(page.get_by_role("heading", name=trap_id, exact=True)).to_be_visible(timeout=30_000)
    page.wait_for_timeout(600)


def action(page: Page, label: str, heading: str) -> None:
    """Open one of the trap page's actions and wait for its page."""
    page.get_by_role("button", name=label, exact=True).click()
    expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible(timeout=30_000)
    page.wait_for_timeout(600)


def tick(page: Page, label: str) -> None:
    box = page.get_by_role("checkbox", name=label, exact=True)
    box.focus()
    page.keyboard.press("Space")
    expect(box).to_be_checked(timeout=10_000)


def fill(page: Page, label: str, text: str) -> None:
    """Type into a field and leave it by tapping the page's title (Tab would land in the next date field and open its calendar over the controls)."""
    box = page.get_by_label(label, exact=True)
    box.fill(text)
    page.locator('[role="heading"][aria-level="1"]').first.click()
    page.wait_for_timeout(600)


def open_data_page(page: Page, title: str) -> None:
    """Data & records, then one of its pages (each is a row on the landing page)."""
    back = page.get_by_role("button", name="Back to Data & records", exact=True)
    if back.count():  # already inside Data & records: its menu item leaves a page of the section where it is, so the way to the list is the back pill
        back.click()
        page.wait_for_timeout(1_200)
    else:
        go_to(page, "Data & records")
    page.get_by_role("button", name=title, exact=True).click()
    expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible(timeout=30_000)
    page.wait_for_timeout(600)
