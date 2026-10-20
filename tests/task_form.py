"""Answering the follow-up task forms (Camera review, Camera issue, Trap not ready) in a browser: the one place that knows how they are laid out.

Tests that drive a task page use these steps instead of their own role clicks, so a change to a form's layout changes this file and not a dozen others. Each step
names what the operator does, not how the page draws it (the option rows and segmented controls are radio groups named by their question; a date and a time are
a pair, found by the pair's name: first, kill, trigger, when)."""
from __future__ import annotations

import re
from datetime import datetime

from playwright.sync_api import Page, expect

import check_form as cf


def open_task(page: Page, url: str, kind: str, trap: str) -> None:
    """From the app's first screen to one task's page, through the navigation and the Follow-ups list."""
    from test_trial_screens import _home  # noqa: PLC0415
    _home(page, url)
    page.get_by_role("link", name=re.compile(r"^Follow-ups")).first.click()
    expect(page.get_by_role("heading", name="Follow-ups", exact=True)).to_be_visible(timeout=30_000)
    row = page.locator('[class*="st-key-listrow_"]').filter(has_text=kind).filter(has_text=trap)
    row.get_by_role("button", name="Review", exact=True).click()
    expect(page.get_by_role("heading", name=kind, exact=True)).to_be_visible(timeout=30_000)
    page.wait_for_timeout(800)


def choose(page: Page, question: str, option: str) -> None:
    """Choose an option in a named group (a row list or a segmented control)."""
    cf.pick(page, question, option)


def set_when(page: Page, pair: str, moment: datetime, fmt: str = "%d/%m/%Y") -> None:
    """Fill a date and time pair. Tab leaves the date field (Escape would discard it) so the calendar is closed before the time is typed; left open it covers the time field."""
    day = page.locator(f'[class*="st-key-pair_{pair}_"] [data-testid="stDateInput"] input')
    day.fill(moment.strftime(fmt))
    page.wait_for_timeout(900)  # typing a date commits it and redraws the page; wait for that before touching anything else
    page.locator('[role="heading"][aria-level="1"]').first.click()  # leaves the date field (its calendar would cover the time field) without a key that could press a button
    page.wait_for_timeout(600)
    clock = page.locator(f'[class*="st-key-pair_{pair}_"] [data-testid="stTimeInput"] input')
    clock.click()
    clock.fill(moment.strftime("%H:%M"))
    page.wait_for_timeout(300)
    clock.press("Enter")
    page.wait_for_timeout(700)


def pair_values(page: Page, pair: str) -> tuple:
    """What a date and time pair shows: (the date field's text, the time field's text)."""
    box = page.locator(f'[class*="st-key-pair_{pair}_"]')
    return (box.locator('[data-testid="stDateInput"] input').input_value(), box.locator('[data-testid="stTimeInput"]').inner_text().strip())


def type_into(page: Page, label: str, text: str) -> None:
    cf.type_into(page, label, text)


def save(page: Page, label: str) -> None:
    page.get_by_role("button", name=label, exact=True).click()
