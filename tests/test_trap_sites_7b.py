"""Phase 7b, Trap sites (TRIAL_LIFECYCLE_BRIEF.md, Trap sites board): a white card per site, a dot and words for status, one number
on the right, one primary button per card, and a count of what is due in the title. Local test data only.

Sites in END_SEED: MAN is running a trial with a visit in progress (3 of 5 traps checked); KAI is running with no trial record;
WAI is running with no trial record too. The seeds below change who was last visited, so each card state shows up."""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from journey_seed import END_SEED  # noqa: E402
from test_trial_model_ui import _serve, _sheet  # noqa: E402
from test_trial_screens import _home  # noqa: E402

PHONE, DESKTOP = {"width": 414, "height": 896}, {"width": 1280, "height": 900}

# MAN in progress (3 of 5). KAI last visited 8 days ago (every 3 days: overdue by 5). WAI has no active traps and no trial.
MIXED = END_SEED + """
    d = app.load_data()
    v = pd.DataFrame([["VIS-KAI-OLD", "KAI", "Op", app.dtstr(app.now() - dt.timedelta(days=8, hours=1)), app.dtstr(app.now() - dt.timedelta(days=8)), "Complete", ""]], columns=app.SHEETS["Visits"])
    d["Visits"] = pd.concat([d["Visits"], v], ignore_index=True)
    for t in d["Traps"][(d["Traps"]["Site ID"] == "WAI") & (d["Traps"]["Status"] == "Active")]["Trap ID"]:
        app.deactivate_trap(d, t, app.now() - dt.timedelta(days=30), "stage", commit=False)
    app.save_data(d)
"""
# MAN in progress. WAI finished a visit a minute ago. KAI has never been visited (due today).
DONE_TODAY = END_SEED + """
    d = app.load_data()
    v = pd.DataFrame([["VIS-WAI-TODAY", "WAI", "Op", app.dtstr(app.now() - dt.timedelta(minutes=2)), app.dtstr(app.now() - dt.timedelta(minutes=1)), "Complete", ""]], columns=app.SHEETS["Visits"])
    d["Visits"] = pd.concat([d["Visits"], v], ignore_index=True)
    app.save_data(d)
"""
# Nothing is due: WAI and KAI both finished a visit a minute ago, MAN is in progress.
NOTHING_DUE = END_SEED + """
    d = app.load_data()
    rows = [[f"VIS-{s}-TODAY", s, "Op", app.dtstr(app.now() - dt.timedelta(minutes=2)), app.dtstr(app.now() - dt.timedelta(minutes=1)), "Complete", ""] for s in ("WAI", "KAI")]
    d["Visits"] = pd.concat([d["Visits"], pd.DataFrame(rows, columns=app.SHEETS["Visits"])], ignore_index=True)
    app.save_data(d)
"""
# MAN has a trial and its visit finished a minute ago (Checked today, tracked); KAI is untracked and never visited (Due today); WAI has no active traps.
CHECKED_TODAY_TRACKED = END_SEED + """
    d = app.load_data()
    d["Visits"].loc[d["Visits"]["Visit ID"] == "VIS-WALK-1", ["Status", "End Time"]] = ["Complete", app.dtstr(app.now() - dt.timedelta(minutes=1))]
    for t in d["Traps"][(d["Traps"]["Site ID"] == "WAI") & (d["Traps"]["Status"] == "Active")]["Trap ID"]:
        app.deactivate_trap(d, t, app.now() - dt.timedelta(days=30), "stage", commit=False)
    app.save_data(d)
"""
NO_SITES = END_SEED + """
    d = app.load_data()
    d["Sites"]["Status"] = "Inactive"
    app.save_data(d)
"""

# What a card says: title, status words and class, the stat and its label, and the status dot's colour next to each design token's.
CARD = """(k) => {
  const c = document.querySelector('.st-key-card_site_' + k); const s = c.querySelector('.r1-status');
  const v = c.querySelector('.r1-stat'); const l = c.querySelector('.r1-stat-label');
  const token = (name) => { const d = document.createElement('div'); d.style.background = getComputedStyle(c).getPropertyValue(name).trim();
    document.body.appendChild(d); const col = getComputedStyle(d).backgroundColor; d.remove(); return col; };
  return {title: c.querySelector('.r1-card-title').innerText, status: s ? s.innerText : null, cls: s ? s.className.replace('r1-status', '').trim() : null,
          dot: s ? getComputedStyle(s, '::before').backgroundColor : null, weight: s ? Number(getComputedStyle(s).fontWeight) : null,
          stat: v ? v.innerText : null, label: l ? l.innerText : null, background: getComputedStyle(c).backgroundColor,
          tokens: {orange: token('--orange'), red: token('--red'), green: token('--green'), grey: token('--ink-50')}};
}"""
# The title row's stat, the primary and tertiary buttons of a card, with their sizes and the card's inner width.
TITLE_STAT = """() => { const t = document.querySelector('.st-key-r1_screen .r1-titlerow'); const v = t.querySelector('.r1-stat'); const l = t.querySelector('.r1-stat-label');
  return {stat: v ? v.innerText : null, label: l ? l.innerText : null}; }"""
BUTTONS = """(k) => { const c = document.querySelector('.st-key-card_site_' + k); const inner = c.querySelector('.r1-titlerow').getBoundingClientRect();
  const token = (name) => { const d = document.createElement('div'); d.style.background = getComputedStyle(c).getPropertyValue(name).trim();
    document.body.appendChild(d); const col = getComputedStyle(d).backgroundColor; d.remove(); return col; };
  const size = (b) => { const r = b.getBoundingClientRect(); const p = b.querySelector('p');
    return {text: b.innerText.trim(), width: Math.round(r.width), height: Math.round(r.height), left: Math.round(r.left - inner.left),
            background: getComputedStyle(b).backgroundColor, ink: p ? getComputedStyle(p).color : null}; };
  const of = (kind) => [...c.querySelectorAll('button[kind="' + kind + '"]')].map(size);
  return {inner: Math.round(inner.width), primary: of('primary'), secondary: of('secondary'), tertiary: of('tertiary'),
          tokens: {orange: token('--orange'), ink05: token('--ink-05'), orangeInk: token('--orange-ink')}}; }"""


def _open(page: Page, url: str) -> None:
    _home(page, url)
    expect(page.locator(".st-key-card_site_MAN")).to_be_visible(timeout=20_000)


def _card(page: Page, site_id: str) -> dict:
    return page.evaluate(CARD, site_id)


# --- the card states -------------------------------------------------------------------------------------------------------

def test_each_card_tells_its_state_with_a_dot_and_words_and_one_number(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, MIXED) as url:
        _open(page, url)
        man, kai, wai = _card(page, "MAN"), _card(page, "KAI"), _card(page, "WAI")
        tokens = man["tokens"]
        # in progress: orange, "3 of 5 Checked"
        assert (man["title"], man["status"], man["cls"], man["stat"], man["label"]) == ("Mangaroa Farm", "In progress", "progress", "3 of 5", "Checked"), man
        assert man["dot"] == tokens["orange"], man
        # overdue: red dot, bold words, the number of traps
        assert (kai["title"], kai["status"], kai["cls"], kai["stat"], kai["label"]) == ("Kaitoke Shed", "Overdue by 5 days", "overdue", "4", "Traps"), kai
        assert kai["dot"] == tokens["red"] and kai["weight"] >= 700, kai
        # no trial running: grey dot, no number at all
        assert (wai["title"], wai["status"], wai["cls"], wai["stat"], wai["label"]) == ("Wairarapa Block", "No trial running", "", None, None), wai
        assert wai["dot"] == tokens["grey"], wai


def test_a_site_due_today_is_orange_and_one_checked_today_is_green_and_not_tinted(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, DONE_TODAY) as url:
        _open(page, url)
        man, kai, wai = _card(page, "MAN"), _card(page, "KAI"), _card(page, "WAI")
        tokens = man["tokens"]
        assert (kai["status"], kai["cls"], kai["stat"], kai["label"]) == ("Due today", "due", "4", "Traps"), kai
        assert kai["dot"] == tokens["orange"], kai
        assert (wai["status"], wai["cls"], wai["stat"], wai["label"]) == ("Checked today", "done", "5", "Traps"), wai
        assert wai["dot"] == tokens["green"], wai
        # the old green card tint for a site done today is gone: every card is the same white
        assert man["background"] == kai["background"] == wai["background"] == "rgb(255, 255, 255)", (man["background"], kai["background"], wai["background"])


def test_the_title_counts_what_is_due_now_and_says_nothing_when_nothing_is(page: Page, tmp_path: Path) -> None:
    page.set_viewport_size(PHONE)
    # Overdue counts as due; a site with a visit in progress and a site with no trial running do not.
    data_dir = tmp_path / "a"; data_dir.mkdir()
    with _serve(data_dir, MIXED) as url:
        _open(page, url)
        assert page.evaluate(TITLE_STAT) == {"stat": "1", "label": "Due now"}
    data_dir = tmp_path / "b"; data_dir.mkdir()
    with _serve(data_dir, DONE_TODAY) as url:
        _open(page, url)
        assert page.evaluate(TITLE_STAT) == {"stat": "1", "label": "Due now"}
    # Nothing due: no number, rather than a "0 Due now". (14 Oct 2026: the label was "Due today"; the figure counts overdue sites too.)
    data_dir = tmp_path / "c"; data_dir.mkdir()
    with _serve(data_dir, NOTHING_DUE) as url:
        _open(page, url)
        assert page.evaluate(TITLE_STAT) == {"stat": None, "label": None}
        assert [_card(page, s)["status"] for s in ("MAN", "KAI", "WAI")] == ["In progress", "Checked today", "Checked today"]


def test_a_title_and_an_empty_list_when_no_site_is_active(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, NO_SITES) as url:
        _home(page, url)
        expect(page.get_by_role("heading", name="Trap sites", exact=True)).to_be_visible(timeout=20_000)
        expect(page.get_by_text("No active trap sites are available. Reactivate a site in Administration → Trial setup.", exact=True)).to_be_visible()
        assert page.locator('[class*="st-key-card_site_"]').count() == 0


# --- the buttons -----------------------------------------------------------------------------------------------------------

def test_the_card_buttons_fill_the_card_on_a_phone_and_keep_their_natural_width_on_desktop(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, DONE_TODAY) as url:
        for viewport in (PHONE, DESKTOP):
            page.set_viewport_size(viewport)
            _open(page, url)
            for site_id in ("MAN", "KAI", "WAI"):
                b = page.evaluate(BUTTONS, site_id)
                every = b["primary"] + b["secondary"] + b["tertiary"]
                where = f"{site_id} at {viewport['width']}: {b}"
                assert len(b["primary"]) + len(b["secondary"]) == 1 and len(b["tertiary"]) == 1, f"a button and a text button. {where}"
                assert all(x["height"] >= 44 for x in every), f"nothing tapped is under 44px. {where}"
                if viewport["width"] <= 700:
                    assert all(abs(x["width"] - b["inner"]) <= 2 for x in every), f"on a phone every button fills the card. {where}"
                else:
                    assert all(x["width"] < b["inner"] / 2 for x in every), f"on desktop a button keeps its natural width. {where}"
                    # 14 Oct 2026 (Trap sites on desktop): the button is at the card's left edge and its text action sits beside it, 20px away,
                    # no longer stacked under it.
                    first, second = (b["primary"] + b["secondary"])[0], b["tertiary"][0]
                    assert abs(first["left"]) <= 2, f"the button sits at the card's left edge. {where}"
                    assert abs(second["left"] - (first["width"] + 20)) <= 3, f"and its text action sits beside it, 20px away. {where}"


def test_a_site_checked_today_offers_start_checking_as_a_secondary_button_and_nothing_else_changed(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, CHECKED_TODAY_TRACKED) as url:
        _open(page, url)
        man, kai, wai = (page.evaluate(BUTTONS, s) for s in ("MAN", "KAI", "WAI"))
        t = man["tokens"]
        # Checked today (a trial is running): no primary at all; Start checking is the grey, orange-ink secondary; Trial overview below
        assert man["primary"] == [] and [x["text"] for x in man["secondary"]] == ["Start checking"] and [x["text"] for x in man["tertiary"]] == ["Trial overview"], man
        assert man["secondary"][0]["background"] == t["ink05"] and man["secondary"][0]["ink"] == t["orangeInk"], man["secondary"]
        # every other state is as it was: an orange primary
        assert [x["text"] for x in kai["primary"]] == ["Start checking"] and kai["secondary"] == [] and kai["primary"][0]["background"] == t["orange"], kai
        assert [x["text"] for x in wai["primary"]] == ["Start trial"] and wai["secondary"] == [] and wai["tertiary"] == [], wai
        # it still does what it did: it starts a new visit and opens the trap list
        visits_before = _sheet(data_dir, "Visits"); assert (visits_before["Site ID"] == "MAN").sum() == 1
        page.locator(".st-key-card_site_MAN").get_by_role("button", name="Start checking", exact=True).click()
        expect(page.get_by_role("button", name="Finish site check")).to_be_visible(timeout=30_000)
        visits = _sheet(data_dir, "Visits"); mine = visits[visits["Site ID"] == "MAN"]
        assert len(mine) == 2 and (mine["Status"] == "In progress").sum() == 1


def test_the_card_buttons_still_go_where_they_went(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, MIXED) as url:
        _open(page, url)
        page.locator(".st-key-card_site_MAN").get_by_role("button", name="Resume checking", exact=True).click()
        expect(page.get_by_role("button", name="Finish site check")).to_be_visible(timeout=30_000)
        _open(page, url)
        page.locator(".st-key-card_site_MAN").get_by_role("button", name="Trial overview", exact=True).click()
        expect(page.get_by_text("Evidence waiting", exact=True)).to_be_visible(timeout=30_000)
        _open(page, url)
        page.locator(".st-key-card_site_KAI").get_by_role("button", name="Start checking", exact=True).click()
        expect(page.get_by_role("button", name="Finish site check")).to_be_visible(timeout=30_000)
        _open(page, url)
        page.locator(".st-key-card_site_KAI").get_by_role("button", name="Track as a trial", exact=True).click()
        # (this seed's Kaitoke runs two products, so the screen is the single-product refusal: the destination is the same page)
        expect(page.get_by_role("heading", name="Track as a trial", exact=True)).to_be_visible(timeout=30_000)
        _open(page, url)
        page.locator(".st-key-card_site_WAI").get_by_role("button", name="Start trial", exact=True).click()
        expect(page.get_by_text("Builds this trial compares", exact=True)).to_be_visible(timeout=30_000)
