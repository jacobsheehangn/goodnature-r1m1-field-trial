from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("R1M1_TEST_URL", "").rstrip("/")
PASSWORD = os.environ.get("R1M1_TEST_PASSWORD", "")
SHOTS = Path(__file__).parent / "screenshots"

pytestmark = pytest.mark.skipif(
    not BASE_URL or not PASSWORD,
    reason="Set R1M1_TEST_URL and R1M1_TEST_PASSWORD to run live tests.",
)

def sign_in(page: Page) -> None:
    page.goto(BASE_URL, wait_until="networkidle")
    password = page.get_by_label(re.compile("password", re.I))
    expect(password).to_be_visible()
    password.fill(PASSWORD)
    page.get_by_role("button", name=re.compile("sign in|log in", re.I)).click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text(re.compile("Trap sites|STAGING", re.I)).first).to_be_visible()

@pytest.mark.parametrize(
    "viewport,name",
    [
        ({"width": 390, "height": 844}, "mobile_390"),
        ({"width": 430, "height": 932}, "mobile_430"),
        ({"width": 1440, "height": 1000}, "desktop_1440"),
    ],
)
def test_login_and_home(page: Page, viewport: dict, name: str) -> None:
    page.set_viewport_size(viewport)
    sign_in(page)
    page.screenshot(path=SHOTS / f"{name}_home.png", full_page=True)

    # Staging banner is present and no horizontal overflow.
    expect(page.get_by_text(re.compile("STAGING", re.I)).first).to_be_visible()
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"
    )
    assert overflow is False

def test_mobile_sidebar_toggle_visible(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page)

    toggle = page.locator(
        '[data-testid="stSidebarCollapsedControl"], '
        '[data-testid="stSidebarCollapseButton"], '
        'header button[aria-label*="sidebar" i]'
    ).first
    expect(toggle).to_be_visible()
    toggle.click()

    expect(page.get_by_text("Trap sites", exact=True)).to_be_visible()
    page.screenshot(path=SHOTS / "mobile_sidebar_open.png", full_page=True)

def test_primary_site_journey_shell(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page)

    expect(page.get_by_text("Hutt River", exact=True)).to_be_visible()
    page.get_by_role("button", name=re.compile("Start checking", re.I)).first.click()
    page.wait_for_load_state("networkidle")

    # Terminology and initial trap page.
    expect(page.get_by_text(re.compile("Trap 1", re.I)).first).to_be_visible()
    assert page.get_by_text(re.compile("Route point", re.I)).count() == 0
    page.screenshot(path=SHOTS / "mobile_first_trap.png", full_page=True)

def test_dead_animal_does_not_request_camera(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page)
    page.get_by_role("button", name=re.compile("Start checking", re.I)).first.click()
    page.wait_for_load_state("networkidle")

    # Choose dead-animal outcome where available.
    dead = page.get_by_text("Dead animal found", exact=True)
    if dead.count() == 0:
        pytest.skip("Dead animal option not available in current seeded journey.")
    dead.click()

    # Embedded camera controls must never appear.
    assert page.locator("video").count() == 0
    assert page.locator('[data-testid="stCameraInput"]').count() == 0
    expect(page.get_by_role("button", name="Add photo")).to_be_visible()
    page.screenshot(path=SHOTS / "mobile_dead_animal_upload_only.png", full_page=True)

def test_selection_controls_not_black(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page)
    page.get_by_role("button", name=re.compile("Start checking", re.I)).first.click()
    page.wait_for_load_state("networkidle")

    radios = page.locator('label[data-baseweb="radio"] > div:first-child')
    if radios.count():
        color = radios.first.evaluate("(el) => getComputedStyle(el).backgroundColor")
        assert color not in {"rgb(0, 0, 0)", "rgba(0, 0, 0, 1)"}
