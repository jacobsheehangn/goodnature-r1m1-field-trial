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

def app_home_marker(page: Page):
    """A marker in the main page, avoiding hidden sidebar and staging duplicates."""
    return page.locator(
        '[data-testid="stMain"] h1, '
        '[data-testid="stMain"] h2, '
        '[data-testid="stMain"] [data-testid="stMarkdownContainer"]'
    ).filter(has_text=re.compile(r"^Trap sites$|Choose the trap site you are visiting today", re.I)).first


def sign_in(page: Page) -> None:
    """Open the live app, tolerate Render cold starts, and sign in when required."""
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=120_000)

    password = page.locator('input[type="password"][aria-label="Password"]').first
    home = app_home_marker(page)

    deadline = time.monotonic() + 120
    submitted = False

    while time.monotonic() < deadline:
        if home.count() and home.is_visible():
            return

        if password.count() and password.is_visible():
            if not submitted:
                password.fill(PASSWORD)
                page.get_by_role(
                    "button",
                    name=re.compile(r"^(sign in|log in)$", re.I),
                ).click()
                submitted = True
            page.wait_for_timeout(500)
            continue

        page.wait_for_timeout(500)

    raise AssertionError(
        "The visible Trap sites home screen did not appear within 120 seconds."
    )



def open_mobile_sidebar(page: Page) -> None:
    """Open the sidebar using a visible, on-screen Streamlit menu control."""
    sidebar_nav = page.get_by_test_id("stSidebar").get_by_text("Trap sites", exact=True)
    if sidebar_nav.count() and sidebar_nav.first.is_visible():
        return

    selectors = [
        '[data-testid="stSidebarCollapsedControl"] button',
        '[data-testid="stSidebarCollapsedControl"]',
        '[data-testid="stSidebarCollapseButton"] button',
        '[data-testid="stSidebarCollapseButton"]',
        '[data-testid*="Sidebar"][role="button"]',
        '[data-testid*="Sidebar"] button',
        'header button[aria-label*="sidebar" i]',
        'header button[aria-label*="menu" i]',
        'button[kind="header"]',
    ]

    viewport = page.viewport_size or {"width": 0, "height": 0}

    for selector in selectors:
        candidates = page.locator(selector)
        for index in range(candidates.count()):
            candidate = candidates.nth(index)
            if not candidate.is_visible():
                continue

            box = candidate.bounding_box()
            if not box:
                continue

            on_screen = (
                box["x"] < viewport["width"]
                and box["y"] < viewport["height"]
                and box["x"] + box["width"] > 0
                and box["y"] + box["height"] > 0
            )
            if not on_screen:
                continue

            candidate.click(force=True)
            try:
                expect(sidebar_nav.first).to_be_visible(timeout=10_000)
                return
            except AssertionError:
                continue

    # Last-resort DOM search for a visible top-left Streamlit control.
    clicked = page.evaluate(
        """() => {
          const nodes = [...document.querySelectorAll('button, [role="button"], [data-testid]')];
          const candidates = nodes.filter((el) => {
            const testid = (el.getAttribute('data-testid') || '').toLowerCase();
            const aria = (el.getAttribute('aria-label') || '').toLowerCase();
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            const visible =
              style.visibility !== 'hidden' &&
              style.display !== 'none' &&
              rect.width > 0 &&
              rect.height > 0 &&
              rect.right > 0 &&
              rect.bottom > 0 &&
              rect.left < innerWidth &&
              rect.top < innerHeight;
            const looksRelevant =
              testid.includes('sidebar') ||
              aria.includes('sidebar') ||
              aria.includes('menu');
            const topLeft = rect.left < 140 && rect.top < 160;
            return visible && looksRelevant && topLeft;
          });
          if (!candidates.length) return false;
          candidates[0].click();
          return true;
        }"""
    )
    if clicked:
        expect(sidebar_nav.first).to_be_visible(timeout=10_000)
        return

    raise AssertionError("No visible on-screen sidebar menu control was found.")




def click_sidebar_nav(page: Page, label: str) -> None:
    """Click the actual sidebar navigation button, not its inner text node."""
    open_mobile_sidebar(page)
    sidebar = page.get_by_test_id("stSidebar")
    label_node = sidebar.get_by_text(label, exact=True).first
    expect(label_node).to_be_visible(timeout=10_000)

    button = label_node.locator("xpath=ancestor::button[1]")
    if button.count() == 0:
        button = label_node.locator("xpath=ancestor::*[@role='button'][1]")
    if button.count() == 0:
        raise AssertionError(f"No clickable sidebar control found for {label!r}.")

    button.scroll_into_view_if_needed()
    button.click(force=True)


def enter_first_available_site(page: Page) -> None:
    """Enter a site regardless of existing persistent staging visit state."""
    expect(app_home_marker(page)).to_be_visible(timeout=30_000)

    action_patterns = [
        r"^Start checking$",
        r"^Continue checking$",
        r"^Resume checking$",
        r"^Open visit$",
    ]

    for pattern in action_patterns:
        action = page.get_by_role("button", name=re.compile(pattern, re.I)).first
        if action.count() and action.is_visible():
            action.scroll_into_view_if_needed()
            action.click(force=True)
            page.wait_for_timeout(800)
            return

    buttons = page.get_by_role("button")
    for index in range(buttons.count()):
        button = buttons.nth(index)
        if not button.is_visible():
            continue
        label = (button.inner_text() or "").strip().lower()
        if "checking" in label or "visit" in label:
            button.scroll_into_view_if_needed()
            button.click(force=True)
            page.wait_for_timeout(800)
            return

    raise AssertionError(
        "No visible site action found. Expected Start checking, Continue checking, "
        "Resume checking, or Open visit."
    )



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
    expect(page.locator(".staging-banner:visible")).to_be_visible(timeout=30_000)
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
    enter_first_available_site(page)
    page.wait_for_load_state("networkidle")

    # Terminology and initial trap page.
    expect(page.get_by_text(re.compile(r"Trap\s+1", re.I)).first).to_be_visible(timeout=30_000)
    assert "route point" not in page.locator("body").inner_text().lower()
    page.screenshot(path=SHOTS / "mobile_first_trap.png", full_page=True)

def test_dead_animal_does_not_request_camera(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page)
    enter_first_available_site(page)
    page.wait_for_load_state("networkidle")

    expect(page.get_by_text(re.compile(r"Trap\s+\d+", re.I)).first).to_be_visible(timeout=30_000)

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
    enter_first_available_site(page)
    page.wait_for_load_state("networkidle")

    expect(page.locator('label[data-baseweb="radio"]').first).to_be_visible(timeout=30_000)
    radios = page.locator('label[data-baseweb="radio"] > div:first-child')
    if radios.count():
        color = radios.first.evaluate("(el) => getComputedStyle(el).backgroundColor")
        assert color not in {"rgb(0, 0, 0)", "rgba(0, 0, 0, 1)"}


def test_performance_metrics_do_not_have_nested_card_borders(page: Page) -> None:
    page.set_viewport_size({"width": 1440, "height": 1000})
    sign_in(page)

    # Open sidebar when needed and navigate to Performance.
    click_sidebar_nav(page, "Performance")
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
