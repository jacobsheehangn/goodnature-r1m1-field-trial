"""While a screen is being changed the old screen is faded and untappable until the new screen's title is drawn, then its leftovers
are hidden (the owner's "six buttons" on Finish site check). That must apply ONLY to the run that changes the screen: never to a
rerun of the same screen (a validation message, a filter) and never to Save check's Saving… and Saved states.

Streamlit marks the previous run's elements stale until the run ends. The app draws a marker (.r1-navmark) in a screen-changing run
only, and the CSS applies only while that marker is current. These tests watch every frame while the server is slowed (what it sends
is delayed, as on a weak signal) and check, frame by frame, what is visible, faded, hidden and tappable."""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from journey_seed import END_SEED  # noqa: E402
from test_trial_model_ui import _serve  # noqa: E402

PHONE = {"width": 390, "height": 664}

# One record per change of what is on screen: the run's marker, whether the new title is drawn, how many of the previous run's elements are
# still visible, how many of those are faded and untappable, whether a "Saving…" button is the current one, and the new screen's buttons.
FRAME_LOG = """() => { window.__frames = []; let last = ''; const t0 = performance.now();
  const visible = (el) => el.getClientRects().length > 0 && getComputedStyle(el).display !== 'none';
  const tick = () => { const m = document.querySelector('section[data-testid="stMain"]');
    const boxes = [...m.querySelectorAll('[data-testid="stElementContainer"]')];
    const fresh = boxes.filter(b => b.getAttribute('data-stale') !== 'true');
    const stale = boxes.filter(b => b.getAttribute('data-stale') === 'true' && visible(b) && b.getBoundingClientRect().height > 0);
    const mark = fresh.some(b => b.querySelector('.r1-navmark'));
    const title = fresh.some(b => [...b.querySelectorAll('h1, .r1-title')].some(visible));
    const faded = stale.filter(b => { const cs = getComputedStyle(b); return +cs.opacity < 0.6 && cs.pointerEvents === 'none'; }).length;
    const untappable = stale.filter(b => getComputedStyle(b).pointerEvents === 'none').length;
    const buttons = (list) => list.flatMap(b => [...b.querySelectorAll('button')]).filter(visible).map(b => b.innerText.trim()).filter(Boolean);
    const saving = buttons(fresh).some(t => /^Saving…/.test(t)), savedPanel = fresh.some(b => /Just saved/.test(b.innerText) && visible(b));
    const key = [mark, title, stale.length, faded, untappable, saving, savedPanel].join('/');
    if (key !== last) { window.__frames.push({ms: Math.round(performance.now() - t0), mark, title, stale: stale.length, faded, untappable, saving, savedPanel,
      staleButtons: buttons(stale).slice(0, 4), freshButtons: buttons(fresh).slice(0, 6)}); last = key; }
    requestAnimationFrame(tick); };
  requestAnimationFrame(tick); }"""


def _slow_the_server(page: Page, delay_ms: int) -> None:
    def route(ws):
        server = ws.connect_to_server()
        server.on_message(lambda message: (time.sleep(delay_ms / 1000), ws.send(message)))
    page.route_web_socket("**/_stcore/stream", route)


def _frames(page: Page) -> list:
    return page.evaluate("window.__frames")


ALL_CHECKED = END_SEED.replace("for t in r1[:3]:", "for t in r1:")


def test_a_changing_screen_fades_the_old_one_then_hides_what_is_left_once_the_new_title_is_drawn(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    _slow_the_server(page, 250)
    with _serve(data_dir, ALL_CHECKED) as url:
        page.goto(url, wait_until="domcontentloaded")
        resume = page.get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).first
        expect(resume).to_be_visible(timeout=90_000); page.wait_for_timeout(2500); resume.click()
        finish = page.get_by_role("button", name=re.compile(r"^Finish site check")); expect(finish).to_be_visible(timeout=90_000); page.wait_for_timeout(4000)
        finish.scroll_into_view_if_needed(); page.evaluate(FRAME_LOG); finish.click()
        page.wait_for_timeout(22_000)
        frames = _frames(page)
    marked = [f for f in frames if f["mark"]]
    assert marked, f"the run that changed the screen never drew the marker: {frames}"
    waiting = [f for f in marked if not f["title"] and f["stale"]]
    assert waiting and all(f["faded"] == f["stale"] and f["untappable"] == f["stale"] for f in waiting), \
        f"until the new title is drawn the old screen is still there, faded and untappable: {waiting}"
    drawn = [f for f in marked if f["title"]]
    assert drawn and all(f["stale"] == 0 for f in drawn), f"once the new title is drawn none of the old screen is left visible: {[f for f in drawn if f['stale']]}"


def test_a_rerun_of_the_same_screen_is_never_faded_hidden_or_frozen(page: Page, tmp_path: Path) -> None:
    """A filter changed in place and answers ticked on the check form: the screen is the same, so the marker is never drawn."""
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    _slow_the_server(page, 120)
    with _serve(data_dir, END_SEED) as url:
        page.goto(url, wait_until="domcontentloaded")
        link = page.get_by_role("link", name=re.compile(r"^Follow-ups")).first
        expect(link).to_be_visible(timeout=90_000); page.wait_for_timeout(2500); link.click()
        expect(page.get_by_role("heading", name="Follow-ups")).to_be_visible(timeout=90_000); page.wait_for_timeout(5000)
        page.evaluate(FRAME_LOG)
        segmented = page.locator('[class*="st-key-seg_followup_priority"] button').filter(has_text="High")
        if segmented.count():
            segmented.first.click()
        else:
            page.get_by_label("Priority").first.click(); page.get_by_role("option", name="High").click()
        page.wait_for_timeout(9000)
        in_place = _frames(page)
        # answers ticked on the check form: every tap is a rerun of the same screen, the form growing as it is answered
        page.get_by_role("link", name=re.compile(r"^Trap sites")).first.click(); page.wait_for_timeout(5000)
        page.get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).first.click()
        page.get_by_role("button", name="Check", exact=True).first.click()
        expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=90_000); page.wait_for_timeout(5000)
        page.evaluate(FRAME_LOG)
        page.get_by_role("radio", name="Trap still set, no animal").check(force=True)
        expect(page.get_by_text("Trap relured, reset and ready?", exact=True)).to_be_visible(timeout=90_000); page.wait_for_timeout(2500)
        page.get_by_role("radio", name="Yes").first.check(force=True); page.wait_for_timeout(6000)
        refused = _frames(page)
    for name, frames in (("a filter changed in place", in_place), ("answers ticked on the check form", refused)):
        assert frames, f"{name}: nothing was recorded"
        # a marker still sitting in the page from the previous run (nothing stale beside it) is harmless: the rule needs both
        bad = [f for f in frames if (f["mark"] and f["stale"]) or f["faded"] or f["untappable"]]
        assert not bad, f"{name}: the screen did not change, so nothing may be marked, faded or frozen: {bad}"


def test_saving_and_saved_are_never_faded_hidden_or_frozen_by_the_screen_change(page: Page, tmp_path: Path) -> None:
    """A real Save check. Run 1 arms the button, run 2 shows Saving… and does the save (same screen), run 3 is the trap list with Just saved."""
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    _slow_the_server(page, 120)
    with _serve(data_dir, END_SEED) as url:
        page.goto(url, wait_until="domcontentloaded")
        resume = page.get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).first
        expect(resume).to_be_visible(timeout=90_000); page.wait_for_timeout(2500); resume.click()
        page.get_by_role("button", name="Check", exact=True).first.click()
        expect(page.get_by_text("What did you find?", exact=True)).to_be_visible(timeout=90_000)
        page.get_by_role("radio", name="Trap still set, no animal").check(force=True)
        expect(page.get_by_text("Trap relured, reset and ready?", exact=True)).to_be_visible(timeout=90_000); page.wait_for_timeout(1500)
        stable = 0
        for _ in range(14):
            radios = page.get_by_role("radio", name="Yes"); todo = [i for i in range(radios.count()) if not radios.nth(i).is_checked()]
            if not todo:
                stable += 1
                if stable >= 3: break
            else:
                stable = 0; radios.nth(todo[0]).check(force=True)
            page.wait_for_timeout(900)
        page.wait_for_timeout(3000)
        page.evaluate(FRAME_LOG)
        page.get_by_role("button", name="Save check").click()
        expect(page.get_by_text("Just saved", exact=False).first).to_be_visible(timeout=90_000); page.wait_for_timeout(3000)
        frames = _frames(page)
    saving = [i for i, f in enumerate(frames) if f["saving"]]
    assert saving, f"the Saving… state was never on screen, so this proves nothing: {frames}"
    # From the tap to the last frame of Saving… is the same screen: the tap re-arms the button, then Saving… shows while the save runs.
    # Nothing in that stretch may be marked beside stale elements, faded or frozen: the Save check button must stay tappable up to the
    # moment it is replaced by Saving…, and Saving… itself is a current element.
    same_screen = frames[: saving[-1] + 1]
    bad = [f for f in same_screen if (f["mark"] and f["stale"]) or f["faded"] or f["untappable"]]
    assert not bad, f"the tap, Saving… and the save are the same screen: no marker beside stale elements, nothing faded or frozen: {bad}"
    saved = [f for f in frames if f["savedPanel"]]
    assert saved, f"the Just saved state was never on screen: {frames}"
    assert all(f["saving"] is False for f in saved), "Saving… and Just saved are never the current screen together"
    assert saved[-1]["stale"] == 0, f"the Saved screen ends with none of the old screen's leftovers: {saved[-1]}"
