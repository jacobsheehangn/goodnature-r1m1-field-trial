"""Phase 7a (TRIAL_LIFECYCLE_BRIEF.md): the visual-language foundation and its Streamlit spike.

Covers: Lato self-hosted (no request to Google), the exact tokens, the icon set, the
components in the pinned Streamlit 1.60.0 (tiles, segmented control, option rows,
a list row that stays on one line on a phone, button states, navigation with the
700px switch), and that 7a changed no real screen (app.py does not use the module)."""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import r1m1_design as design  # noqa: E402

TOKENS = {
    "--page": "#ffffff", "--ink": "#000000", "--ink-70": "rgba(0,0,0,.70)", "--ink-50": "rgba(0,0,0,.50)",
    "--ink-10": "rgba(0,0,0,.10)", "--ink-05": "rgba(0,0,0,.05)",
    "--orange": "#f37021", "--orange-10": "rgba(243,112,33,.10)", "--orange-50": "rgba(243,112,33,.50)", "--orange-ink": "#b84808",
    "--green": "#0da84b", "--green-10": "rgba(13,168,75,.10)", "--red": "#fe012c", "--red-10": "rgba(254,1,44,.10)",
    "--shadow-panel": "0 0 100px rgba(0,0,0,.05),0 0 20px rgba(0,0,0,.05),0 0 0 1px rgba(0,0,0,.05)",
    "--shadow-segment": "0 0 0 1px rgba(0,0,0,.05),0 1px 4px rgba(0,0,0,.12)",
    "--r-card": "20px", "--r-panel": "14px", "--r-segment": "12px", "--r-input": "10px", "--r-check": "8px", "--r-pill": "999px",
    "--font": "'Lato',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
}


def test_tokens_are_exactly_the_specified_values() -> None:
    found = dict(re.findall(r"(--[a-z0-9-]+):([^;]+);", design.TOKENS_CSS))
    assert found == TOKENS


def test_fonts_are_self_hosted_400_and_700_only_with_the_licence_beside_them() -> None:
    css = design.design_css()
    assert "googleapis" not in css and "gstatic" not in css and "http" not in css.replace("http://www.w3.org", "")
    faces = re.findall(r"@font-face\{[^}]*\}", css)
    assert len(faces) == 4
    assert {re.search(r"font-weight:(\d+)", f).group(1) for f in faces} == {"400", "700"}
    assert all("font-display:swap" in f and "/app/static/fonts/" in f for f in faces)
    for face in faces:
        path = ROOT / "static" / "fonts" / re.search(r"/fonts/([^)]+\.woff2)", face).group(1)
        assert path.is_file() and path.stat().st_size > 1000, path
    licence = (ROOT / "static" / "fonts" / "OFL.txt").read_text()
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence
    assert "enableStaticServing = true" in (ROOT / ".streamlit" / "config.toml").read_text()
    # latin-ext carries the macrons in Maori place names.
    assert "U+0100-02BA" in design.FONT_FACE_CSS


def test_every_icon_the_css_uses_exists_and_the_set_is_line_icons_without_emoji() -> None:
    for name in set(re.findall(r"/app/static/icons/([a-z-]+)\.svg", design.design_css())):
        assert (ROOT / "static" / "icons" / f"{name}.svg").is_file(), name
    for name, svg in design.ICONS.items():
        assert 'stroke="currentColor"' in svg and 'stroke-linecap="round"' in svg, name
        assert not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", svg), name
    for needed in ("rat", "mouse", "hedgehog", "stoat", "squirrel", "cat", "question", "camera", "bag", "spinner", "check", "arrow-left"):
        assert needed in design.ICONS
    assert 'width="22" height="22"' in design.icon("check-circle", 22)


def test_phase_7a_changes_no_real_screen() -> None:
    assert "r1m1_design" not in (ROOT / "app.py").read_text(), "7a is foundation and spike only; screens adopt it in 7b / Phases 2-6"


# ----------------------------------------------------------------- the spike in a browser ---

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def spike_url():
    port = _free_port()
    env = dict(os.environ, STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "phase7a_spike.py", "--server.address", "127.0.0.1", "--server.port", str(port),
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    try:
        while True:
            try:
                urllib.request.urlopen(f"{url}/_stcore/health", timeout=2)
                break
            except Exception:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("spike did not start")
                time.sleep(0.25)
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _open(page: Page, url: str, path: str = "/", width: int = 390, height: int = 3000) -> list:
    requests: list = []
    page.on("request", lambda r: requests.append(r.url))
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url + path, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(".st-key-app_nav")).to_be_attached(timeout=30_000)
    page.wait_for_timeout(1200)
    return requests


def test_the_spike_renders_in_lato_from_the_app_with_no_request_to_google(page: Page, spike_url: str) -> None:
    requests = _open(page, spike_url)
    fonts = page.evaluate("""() => ({h1: getComputedStyle(document.querySelector('h1')).fontFamily,
        label: getComputedStyle(document.querySelector('[data-testid="stWidgetLabel"] p')).fontFamily,
        button: getComputedStyle(document.querySelector('button p')).fontFamily,
        loaded: [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family + ' ' + f.weight)})""")
    assert fonts["h1"].startswith("Lato") and fonts["label"].startswith("Lato") and fonts["button"].startswith("Lato")
    assert "Lato 400" in fonts["loaded"] and "Lato 700" in fonts["loaded"]
    external = {u.split("/")[2] for u in requests if u.startswith("http") and "127.0.0.1" not in u}
    assert external == set(), f"the page must make no request outside the app, got {external}"


@pytest.mark.parametrize("width", [360, 390])
def test_components_meet_the_tap_and_layout_rules_on_a_phone(page: Page, spike_url: str, width: int) -> None:
    _open(page, spike_url, width=width)
    m = page.evaluate("""() => {
      const h = sel => [...document.querySelectorAll(sel)].map(e => Math.round(e.getBoundingClientRect().height));
      const rows = [...document.querySelectorAll('[class*="st-key-listrow_"]')].map(r => {
        const t = r.querySelector('.r1-row-title').getBoundingClientRect(), b = r.querySelector('button').getBoundingClientRect();
        return Math.abs((t.top + t.height / 2) - (b.top + b.height / 2)) < 30 && b.left > t.right - 1;
      });
      const tiles = [...document.querySelectorAll('.st-key-species_a [data-testid="stRadioOption"]')].map(e => Math.round(e.getBoundingClientRect().top));
      return {tile_h: h('.st-key-species_a [data-testid="stRadioOption"]'), tiles_one_row: new Set(tiles).size === 1,
        option_h: h('.st-key-rows_c [data-testid="stRadioOption"]'), seg_h: h('.st-key-seg_a button[role="radio"]'),
        nav_h: h('.st-key-nav_phone [data-testid="stPageLink"] a, .st-key-nav_phone [data-testid="stPopoverButton"]'),
        primary_h: h('button[kind="primary"]'), secondary_h: h('button[kind="secondary"]').filter(x => x > 0), rows_one_line: rows,
        overflow: document.querySelector('[data-testid="stMain"]').scrollWidth > document.querySelector('[data-testid="stMain"]').clientWidth + 1};
    }""")
    assert m["tiles_one_row"] and min(m["tile_h"]) >= 96 and len(m["tile_h"]) == 4, "four tiles across, at least 96px tall"
    assert min(m["option_h"]) >= 56 and min(m["seg_h"]) >= 44 and min(m["nav_h"]) >= 44
    assert min(m["primary_h"]) >= 48 and min(m["secondary_h"]) >= 44
    assert all(m["rows_one_line"]) and len(m["rows_one_line"]) == 3, "a list row stays on one line on a phone"
    assert m["overflow"] is False


def test_selected_tile_and_option_row_use_the_selected_treatment(page: Page, spike_url: str) -> None:
    _open(page, spike_url)
    page.locator('.st-key-species_a [data-testid="stRadioOption"]').nth(1).click()
    selected = page.locator('.st-key-species_a [data-testid="stRadioOption"]:has(input:checked)')
    expect(selected).to_have_count(1, timeout=10_000)
    expect(selected).to_contain_text("Mouse")
    style = selected.evaluate("e => ({bg: getComputedStyle(e).backgroundColor, ring: getComputedStyle(e).boxShadow, w: getComputedStyle(e.querySelector('p')).fontWeight})")
    assert style["bg"].startswith("rgba(243, 112, 33") and "rgb(243, 112, 33)" in style["ring"] and style["w"] == "700"
    page.locator('.st-key-rows_c [data-testid="stRadioOption"]').nth(2).click()
    expect(page.locator('.st-key-rows_c [data-testid="stRadioOption"]:has(input:checked)')).to_contain_text("Could not assess", timeout=10_000)


def test_segmented_control_needs_a_choice_until_one_is_made(page: Page, spike_url: str) -> None:
    _open(page, spike_url)
    group = page.locator('.st-key-seg_choose_b [role="radiogroup"]')
    assert "rgb(243, 112, 33)" in group.evaluate("e => getComputedStyle(e).boxShadow")
    expect(page.get_by_text("Choose a build", exact=True)).to_be_visible()
    page.locator('.st-key-seg_choose_b button[role="radio"]').nth(1).click()
    expect(page.get_by_text("Choose a build", exact=True)).to_have_count(0, timeout=10_000)
    assert "rgb(243, 112, 33)" not in group.evaluate("e => getComputedStyle(e).boxShadow")


def test_saving_button_is_full_orange_with_a_spinner_and_done_is_green(page: Page, spike_url: str) -> None:
    _open(page, spike_url)
    saving = page.locator(".st-key-save_saving button")
    assert saving.is_disabled() and saving.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(243, 112, 33)"
    assert saving.evaluate("e => getComputedStyle(e, '::before').animationName") == "r1spin"
    done = page.locator(".st-key-save_done button")
    assert done.is_disabled() and done.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(13, 168, 75)"
    plain_disabled = page.locator(".st-key-finish_disabled button")
    assert plain_disabled.evaluate("e => getComputedStyle(e).backgroundColor") == "rgba(243, 112, 33, 0.5)"


def test_navigation_is_one_row_on_a_phone_four_items_on_desktop_and_switches_at_700px(page: Page, spike_url: str) -> None:
    _open(page, spike_url, width=700, height=600)
    state = page.evaluate("() => [getComputedStyle(document.querySelector('.st-key-nav_phone')).display !== 'none', getComputedStyle(document.querySelector('.st-key-nav_desktop')).display !== 'none']")
    assert state == [True, False]
    labels = page.locator(".st-key-nav_phone [data-testid='stPageLink'] a, .st-key-nav_phone [data-testid='stPopoverButton']").all_inner_texts()
    assert [t.split("\n")[0].strip() for t in labels] == ["Trap sites", "Follow-ups", "More"]
    tops = page.evaluate("() => [...document.querySelectorAll('.st-key-nav_phone a, .st-key-nav_phone [data-testid=\"stPopoverButton\"]')].map(e => Math.round(e.getBoundingClientRect().top))")
    assert len(set(tops)) == 1, "one row"
    page.set_viewport_size({"width": 701, "height": 600})
    page.wait_for_timeout(300)
    state = page.evaluate("() => [getComputedStyle(document.querySelector('.st-key-nav_phone')).display !== 'none', getComputedStyle(document.querySelector('.st-key-nav_desktop')).display !== 'none']")
    assert state == [False, True]
    labels = page.locator(".st-key-nav_desktop [data-testid='stPageLink'] a, .st-key-nav_desktop [data-testid='stPopoverButton']").all_inner_texts()
    assert [t.split("\n")[0].strip() for t in labels] == ["Trap sites", "Follow-ups", "Trial performance", "Administration"]


def test_current_section_is_shown_by_the_disabled_link_and_the_follow_ups_count(page: Page, spike_url: str) -> None:
    _open(page, spike_url, "/follow-ups", width=390, height=700)
    current = page.locator(".st-key-nav_phone a[href$='follow-ups']")
    assert current.get_attribute("disabled") is not None, "the shipped disabled-link mechanism is kept"
    style = current.evaluate("e => ({ring: getComputedStyle(e).boxShadow, weight: getComputedStyle(e.querySelector('p')).fontWeight, badge: getComputedStyle(e, '::after').content, badge_bg: getComputedStyle(e, '::after').backgroundColor})")
    assert "rgb(243, 112, 33)" in style["ring"] and style["weight"] == "700" and style["badge"] == '"3"'
    assert style["badge_bg"] == "rgb(255, 255, 255)", "the count turns white inside its own current pill"
    # A page inside More gives the More pill the current state.
    page.goto(spike_url + "/data-quality", wait_until="domcontentloaded")
    expect(page.locator(".st-key-navmore_on_phone")).to_be_attached(timeout=30_000)
    more = page.locator(".st-key-navmore_on_phone [data-testid='stPopoverButton']")
    assert "rgb(243, 112, 33)" in more.evaluate("e => getComputedStyle(e).boxShadow")
    more.click()
    expect(page.locator("[data-testid='stPopoverBody'] a[href$='data-quality']")).to_be_visible(timeout=10_000)
    for label in ("Trial performance", "Traps", "Trial setup", "Data & records", "Data quality"):
        expect(page.locator("[data-testid='stPopoverBody']").get_by_text(label, exact=True)).to_be_visible()
    expect(page.locator("[data-testid='stPopoverBody']").get_by_role("button", name="Sign out")).to_be_visible()
