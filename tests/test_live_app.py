from __future__ import annotations

import os
import re
import time
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
    """Open the live app, tolerate Render cold starts, and sign in when required."""
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=120_000)

    password = page.locator('input[type="password"][aria-label="Password"]').first
    home = page.get_by_text("Trap sites", exact=True)
    staging = page.get_by_text(re.compile("STAGING", re.I)).first

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if home.count() and home.first.is_visible():
            return
        if password.count() and password.is_visible():
            password.fill(PASSWORD)
            page.get_by_role(
                "button",
                name=re.compile(r"^(sign in|log in)$", re.I),
            ).click()
            expect(staging.or_(home.first)).to_be_visible(timeout=60_000)
            return
        page.wait_for_timeout(500)

    raise AssertionError("Neither the login form nor the signed-in home screen appeared within 120 seconds.")

def open_mobile_sidebar(page: Page) -> None:
    """Open the sidebar using only a visible, on-screen toggle."""
    sidebar_nav = page.get_by_text("Trap sites", exact=True)
    if sidebar_nav.count() and sidebar_nav.first.is_visible():
        return

    candidates = page.locator(
        '[data-testid="stSidebarCollapsedControl"] button, '
        '[data-testid="stSidebarCollapsedControl"], '
        'header button[aria-label*="sidebar" i], '
        'button[kind="header"]'
    )

    for index in range(candidates.count()):
        candidate = candidates.nth(index)
        if not candidate.is_visible():
            continue
        box = candidate.bounding_box()
        if not box:
            continue
        viewport = page.viewport_size or {"width": 0, "height": 0}
        on_screen = (
            box["x"] < viewport["width"]
            and box["y"] < viewport["height"]
            and box["x"] + box["width"] > 0
            and box["y"] + box["height"] > 0
        )
        if on_screen:
            candidate.click(force=True)
            expect(sidebar_nav.first).to_be_visible(timeout=10_000)
            return

    raise AssertionError("No visible on-screen sidebar toggle was found.")



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

    open_mobile_sidebar(page)
    expect(page.get_by_text("Trap sites", exact=True).first).to_be_visible()
    page.screenshot(path=SHOTS / "mobile_sidebar_open.png", full_page=True)

def test_primary_site_journey_shell(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page)

    expect(page.get_by_text("Hutt River", exact=True)).to_be_visible()
    page.get_by_role("button", name=re.compile("Start checking", re.I)).first.click()
    page.wait_for_load_state("networkidle")

    # Terminology and initial trap page.
    expect(page.get_by_text(re.compile("Trap 1", re.I)).first).to_be_visible()
    assert "route point" not in page.locator("body").inner_text().lower()
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


def test_performance_metrics_do_not_have_nested_card_borders(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 1000})
    sign_in(page)

    # Open sidebar when needed and navigate to Performance.
    performance = page.get_by_text("Performance", exact=True)
    if not (performance.count() and performance.first.is_visible()):
        open_mobile_sidebar(page)
    expect(performance.first).to_be_visible(timeout=10_000)
    performance.first.click()
    expect(page.get_by_text("Performance at a glance", exact=True)).to_be_visible(timeout=30_000)

    metrics = page.locator('[data-testid="stMetric"]')
    expect(metrics.first).to_be_visible()

    for index in range(metrics.count()):
        metric = metrics.nth(index)
        border_width = metric.evaluate(
            "(el) => getComputedStyle(el).borderTopWidth"
        )
        box_shadow = metric.evaluate(
            "(el) => getComputedStyle(el).boxShadow"
        )
        assert border_width == "0px"
        assert box_shadow in {"none", ""}
