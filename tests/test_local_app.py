from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect


SHOTS = Path(__file__).parent / "screenshots"


def open_home(page: Page, local_app: str, viewport: dict) -> None:
    page.set_viewport_size(viewport)
    page.goto(local_app, wait_until="domcontentloaded", timeout=60_000)

    home = page.get_by_text("Trap sites", exact=True).last
    expect(home).to_be_visible(timeout=30_000)


@pytest.mark.parametrize(
    "viewport,name",
    [
        ({"width": 390, "height": 844}, "mobile_390"),
        ({"width": 430, "height": 932}, "mobile_430"),
        ({"width": 1440, "height": 1000}, "desktop_1440"),
    ],
)
def test_home_renders_without_horizontal_overflow(
    page: Page, local_app: str, viewport: dict, name: str
) -> None:
    open_home(page, local_app, viewport)
    page.screenshot(path=SHOTS / f"{name}_home.png", full_page=True)

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"
    )
    assert overflow is False


def test_clean_seed_starts_first_site_journey(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})

    expect(page.get_by_text("Hutt River", exact=True)).to_be_visible()
    start = page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first
    expect(start).to_be_visible(timeout=10_000)
    start.click()

    expect(page.get_by_text(re.compile(r"Trap\s+1", re.I)).first).to_be_visible(
        timeout=30_000
    )
    assert "route point" not in page.locator("body").inner_text().lower()
    page.screenshot(path=SHOTS / "mobile_first_trap.png", full_page=True)


def test_dead_animal_uses_upload_not_embedded_camera(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})

    page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first.click()
    expect(page.get_by_text(re.compile(r"Trap\s+1", re.I)).first).to_be_visible(
        timeout=30_000
    )

    dead = page.get_by_text("Dead animal found", exact=True)
    if dead.count() == 0:
        pytest.skip("Dead animal option is not present in this clean-seed screen.")
    dead.click()

    assert page.locator("video").count() == 0
    assert page.locator('[data-testid="stCameraInput"]').count() == 0
    expect(page.get_by_role("button", name="Add photo")).to_be_visible(timeout=10_000)
    page.screenshot(path=SHOTS / "mobile_dead_animal_upload_only.png", full_page=True)


def test_traps_page_is_available_from_main_navigation(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 1440, "height": 1000})

    sidebar = page.get_by_test_id("stSidebar")
    history_label = sidebar.get_by_text("Traps", exact=True)
    expect(history_label).to_be_visible(timeout=10_000)

    button = history_label.locator("xpath=ancestor::button[1]")
    expect(button).to_be_visible(timeout=10_000)
    button.click()

    expect(page.get_by_text("Traps", exact=True).last).to_be_visible(
        timeout=20_000
    )
    expect(page.get_by_text(re.compile(r"\d+\s+kills?", re.I)).first).to_be_visible(
        timeout=10_000
    )


def test_navigation_uses_approved_labels(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 1440, "height": 1000})

    sidebar = page.get_by_test_id("stSidebar")
    for label in ["Trap sites", "Traps", "Follow-ups", "Trial performance"]:
        expect(sidebar.get_by_text(label, exact=True)).to_be_visible(timeout=10_000)

    expect(sidebar.get_by_text("Administration", exact=True)).to_be_visible(
        timeout=10_000
    )

    # Old labels must not remain in the visible main navigation.
    visible_sidebar_text = sidebar.inner_text()
    assert "Trap history" not in visible_sidebar_text
    assert "Follow-up tasks" not in visible_sidebar_text
    assert "\nPerformance\n" not in f"\n{visible_sidebar_text}\n"


@pytest.mark.parametrize(
    "viewport",
    [
        {"width": 390, "height": 844},
        {"width": 1440, "height": 1000},
    ],
)
def test_trap_detail_opens_as_a_page_and_returns_to_list(
    page: Page, local_app: str, viewport: dict
) -> None:
    open_home(page, local_app, viewport)

    sidebar = page.get_by_test_id("stSidebar")
    traps_label = sidebar.get_by_text("Traps", exact=True)
    traps_label.locator("xpath=ancestor::button[1]").click()

    expect(page.get_by_text("Traps", exact=True).last).to_be_visible(timeout=20_000)
    view = page.get_by_role("button", name="View").first
    expect(view).to_be_visible(timeout=10_000)
    view.click()

    expect(
        page.get_by_role("button", name=re.compile("Back to traps", re.I))
    ).to_be_visible(timeout=20_000)
    expect(page.get_by_text("Full history", exact=True)).to_be_visible(timeout=10_000)
    assert page.get_by_role("button", name="View").count() == 0

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"
    )
    assert overflow is False

    page.get_by_role("button", name=re.compile("Back to traps", re.I)).click()
    expect(page.get_by_text("Traps", exact=True).last).to_be_visible(timeout=20_000)
    expect(page.get_by_role("button", name="View").first).to_be_visible(timeout=10_000)


def test_trap_list_filters_survive_detail_navigation(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 1440, "height": 1000})

    sidebar = page.get_by_test_id("stSidebar")
    sidebar.get_by_text("Traps", exact=True).locator("xpath=ancestor::button[1]").click()

    search = page.get_by_label("Find trap")
    search.fill("HUT")
    expect(page.get_by_role("button", name="View").first).to_be_visible(timeout=10_000)

    page.get_by_role("button", name="View").first.click()
    page.get_by_role("button", name=re.compile("Back to traps", re.I)).click()

    expect(page.get_by_label("Find trap")).to_have_value("HUT")


def test_mobile_main_navigation_closes_sidebar(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})

    sidebar = page.get_by_test_id("stSidebar")

    if not sidebar.is_visible():
        controls = page.locator(
            '[data-testid="stSidebarCollapsedControl"] button, '
            '[data-testid="stSidebarCollapsedControl"], '
            'button[aria-label*="sidebar" i], '
            'button[aria-label*="menu" i]'
        )
        for index in range(controls.count()):
            control = controls.nth(index)
            if control.is_visible():
                control.click(force=True)
                break

    expect(sidebar).to_be_visible(timeout=10_000)

    traps_label = sidebar.get_by_text("Traps", exact=True)
    traps_label.locator("xpath=ancestor::button[1]").click(force=True)

    expect(page.get_by_text("Traps", exact=True).last).to_be_visible(timeout=20_000)

    page.wait_for_function(
        """() => {
          const sidebar = document.querySelector('[data-testid="stSidebar"]');
          if (!sidebar) return true;
          const rect = sidebar.getBoundingClientRect();
          const style = getComputedStyle(sidebar);
          return (
            style.display === 'none' ||
            style.visibility === 'hidden' ||
            sidebar.getAttribute('aria-hidden') === 'true' ||
            rect.width <= 20 ||
            rect.right <= 0
          );
        }""",
        timeout=8_000,
    )
