"""Phase 7b, Trap list (visit mode): TrapList and SavedConfirm boards. One narrow column with no top navigation and a back pill; the title with
"3 of 5 Checked" and a thin progress bar; the traps still to check in one card (the next one highlighted with the orange Check, the rest grey), the
checked traps in another (newest first, with when and what was found); a Finish site check that says why it is disabled. Local test data only.

MAN is running a trial with a visit in progress: 5 traps, 3 checked at 9:00 am ("Trap still set, no animal")."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from journey_seed import END_SEED  # noqa: E402
from test_trial_model_ui import _serve  # noqa: E402
from test_trial_screens import _card, _home  # noqa: E402

PHONE, DESKTOP = {"width": 414, "height": 896}, {"width": 1280, "height": 900}
FINISH = re.compile(r"^Finish site check")

# Two builds compared: every other trap is on an older build.
TWO_BUILDS = END_SEED + """
    d = app.load_data()
    mine = d["Traps"][(d["Traps"]["Site ID"] == "MAN") & (d["Traps"]["Product"] == "R1")]["Trap ID"].tolist()
    for t in mine[1::2]:
        d["Traps"].loc[d["Traps"]["Trap ID"] == t, "Build Version"] = "R1 Build 4.1"
    app.save_data(d)
"""
# The first checked trap found a dead rat, twenty minutes ago (the other two were checked at 9:00 am on 5 Oct, so it is the newest).
KILL_CHECKED = END_SEED + """
    d = app.load_data()
    first = d["Checks"][d["Checks"]["Visit ID"] == "VIS-WALK-1"].index[0]
    d["Checks"].loc[first, ["Finding", "Species", "Check Time"]] = ["Dead animal found", "Rat", app.dtstr(app.now() - dt.timedelta(minutes=20))]
    app.save_data(d)
"""
NOTHING_CHECKED = END_SEED + """
    d = app.load_data()
    d["Checks"] = d["Checks"][d["Checks"]["Visit ID"] != "VIS-WALK-1"].copy()
    app.save_data(d)
"""
ALL_CHECKED = END_SEED.replace("for t in r1[:3]:", "for t in r1:")

ROWS = """() => ({
  toCheck: [...document.querySelectorAll('[class*="st-key-listrow_"][class*="visit_"]')].map(r => ({
    key: [...r.classList].find(c => c.startsWith('st-key-')), text: r.innerText.replace(/\\s+/g, ' ').trim(),
    button: (b => b ? {kind: b.getAttribute('kind'), text: b.innerText.trim(), h: Math.round(b.getBoundingClientRect().height), top: Math.round(b.getBoundingClientRect().top)} : null)(r.querySelector('button')),
    titleTop: Math.round(r.querySelector('.r1-row-title').getBoundingClientRect().top)})),
  checked: [...document.querySelectorAll('.r1-donerow')].map(r => ({text: r.innerText.replace(/\\s+/g, ' ').trim(), cls: r.className, tile: r.querySelector('.r1-donebox').innerHTML})),
  stat: (e => e ? [e.innerText, e.nextElementSibling.innerText] : null)(document.querySelector('.st-key-r1_screen .r1-titlerow .r1-stat')),
  bar: (b => b ? {now: b.getAttribute('aria-valuenow'), max: b.getAttribute('aria-valuemax'), fill: b.firstElementChild.style.width} : null)(document.querySelector('.r1-bar')),
  headings: [...document.querySelectorAll('.r1-label')].map(e => e.innerText),
  navigation: document.querySelectorAll('.st-key-nav_desktop, .st-key-nav_phone, .st-key-app_nav').length,
  body: document.body.innerText,
})"""


def _open_visit(page: Page, url: str) -> None:
    _home(page, url)
    _card(page, "Mangaroa Farm").get_by_role("button", name=re.compile(r"^(Resume|Start) checking$")).click()
    expect(page.get_by_role("button", name=FINISH)).to_be_visible(timeout=30_000)
    page.wait_for_timeout(600)


def test_the_list_shows_progress_the_next_trap_and_the_checked_traps_newest_first(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, KILL_CHECKED) as url:
        _open_visit(page, url)
        v = page.evaluate(ROWS)
        assert v["stat"] == ["3 of 5", "Checked"], v["stat"]
        assert v["bar"] == {"now": "3", "max": "5", "fill": "60%"}, v["bar"]
        # the two traps still to check: the next one highlighted with the orange Check, the other grey
        assert [r["text"].split(" ")[0] for r in v["toCheck"]] == ["R1-MAN-005", "R1-MAN-006"], v["toCheck"]
        assert "listrow_next" in v["toCheck"][0]["key"] and "listrow_next" not in v["toCheck"][1]["key"]
        assert [r["button"]["kind"] for r in v["toCheck"]] == ["primary", "secondary"] and all(r["button"]["text"] == "Check" for r in v["toCheck"])
        # the checked traps, newest first: the kill (20 minutes ago) before the two at 9:00 am; what was found and when
        assert v["headings"] == ["Checked"]
        assert [c["text"].split(" ")[0] for c in v["checked"]] == ["R1-MAN-001", "R1-MAN-002", "R1-MAN-003"], v["checked"]
        assert re.fullmatch(r"R1-MAN-001 Checked \d{1,2}:\d{2} [ap]m · Dead animal found · Rat", v["checked"][0]["text"]), v["checked"][0]["text"]
        assert v["checked"][1]["text"] == "R1-MAN-002 Checked 9:00 am · Trap still set, no animal", v["checked"][1]["text"]
        assert v["checked"][0]["tile"] != v["checked"][1]["tile"] == v["checked"][2]["tile"], "a kill has its species icon; the others a check"


def test_a_build_shows_on_a_row_only_when_the_list_compares_builds(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size(PHONE)
    data_dir = tmp_path / "one"; data_dir.mkdir()
    with _serve(data_dir, END_SEED) as url:
        _open_visit(page, url)
        assert "Build" not in " ".join(r["text"] for r in page.evaluate(ROWS)["toCheck"]), "one build: no build on any row"
    data_dir = tmp_path / "two"; data_dir.mkdir()
    with _serve(data_dir, TWO_BUILDS) as url:
        _open_visit(page, url)
        rows = page.evaluate(ROWS)["toCheck"]
        assert [r["text"] for r in rows] == ["R1-MAN-005 Build 4.1 Check", "R1-MAN-006 Build 4.3 Check"], rows


def test_the_clutter_the_brief_removes_is_gone_and_the_page_has_a_back_pill_and_no_navigation(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, END_SEED) as url:
        _open_visit(page, url)
        v = page.evaluate(ROWS)
        for gone in ("Select the trap you are standing at", "Route ", "Not checked", "Site check actions", "Pause and return", "traps checked", "Last ", "Next due"):
            assert gone not in v["body"], f"{gone!r} should be gone from the trap list"
        assert v["navigation"] == 0, "visit mode has no top navigation"
        pill = page.get_by_role("button", name="Exit to Trap sites")
        expect(pill).to_be_visible()
        assert pill.evaluate("e => e.closest('[class*=\"st-key-back_\"]') !== null"), "it is the 7a back pill"
        pill.click()
        expect(page.get_by_role("heading", name="Trap sites", exact=True)).to_be_visible(timeout=30_000)


def test_finish_site_check_says_why_it_is_disabled_and_enables_when_every_trap_is_checked(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size(PHONE)
    data_dir = tmp_path / "a"; data_dir.mkdir()
    with _serve(data_dir, NOTHING_CHECKED) as url:
        _open_visit(page, url)
        assert page.get_by_role("button", name=FINISH).is_disabled()
        expect(page.get_by_text("5 traps still to check.", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Cancel check")).to_be_visible()
        assert page.get_by_role("button", name=re.compile("Finish visit and end trial")).count() == 0, "nothing checked yet: no end-trial route"
    data_dir = tmp_path / "b"; data_dir.mkdir()
    with _serve(data_dir, END_SEED) as url:
        _open_visit(page, url)
        assert page.get_by_role("button", name=FINISH).is_disabled()
        expect(page.get_by_text("2 traps still to check.", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name=re.compile("Finish visit and end trial"))).to_be_visible()
        assert page.get_by_role("button", name="Cancel check").count() == 0, "a trap is checked: Cancel check is gone"
    data_dir = tmp_path / "c"; data_dir.mkdir()
    with _serve(data_dir, ALL_CHECKED) as url:
        _open_visit(page, url)
        assert page.get_by_role("button", name=FINISH).is_enabled()
        assert page.get_by_text(re.compile(r"still to check")).count() == 0, "nothing left to say once it is enabled"
        assert page.evaluate(ROWS)["toCheck"] == [], "every trap is in the Checked card"


def test_it_is_one_narrow_column_with_full_width_buttons_on_a_phone_and_natural_width_on_desktop(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, END_SEED) as url:
        for viewport in (PHONE, DESKTOP):
            page.set_viewport_size(viewport)
            _open_visit(page, url)
            v = page.evaluate(ROWS)
            where = f"at {viewport['width']}"
            assert all(r["button"]["h"] >= 44 for r in v["toCheck"]), f"every Check is at least 44px tall {where}"
            assert all(abs(r["button"]["top"] - r["titleTop"]) < 40 for r in v["toCheck"]), f"the trap and its Check share a line {where}"
            screen_w = page.evaluate("document.querySelector('.st-key-r1_screen').getBoundingClientRect().width")
            finish = page.get_by_role("button", name=FINISH).bounding_box()
            if viewport["width"] <= 700:
                assert abs(finish["width"] - screen_w) <= 2, f"Finish fills the column {where}"
            else:
                assert screen_w <= 761, f"one narrow column {where}: {screen_w}"
                assert finish["width"] < screen_w / 2, f"Finish keeps its natural width {where}"
