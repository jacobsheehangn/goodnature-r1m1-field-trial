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


def test_selection_controls_are_not_solid_black(page: Page, local_app: str) -> None:
    open_home(page, local_app, {"width": 390, "height": 844})

    page.get_by_role("button", name=re.compile(r"^Start checking$", re.I)).first.click()
    expect(page.get_by_text(re.compile(r"Trap\s+1", re.I)).first).to_be_visible(
        timeout=30_000
    )

    radios = page.locator('label[data-baseweb="radio"] > div:first-child')
    expect(radios.first).to_be_visible(timeout=10_000)
    color = radios.first.evaluate("(el) => getComputedStyle(el).backgroundColor")
    assert color not in {"rgb(0, 0, 0)", "rgba(0, 0, 0, 1)"}
