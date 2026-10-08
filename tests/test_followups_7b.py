"""Phase 7b, Follow-ups: the list is a title with the open count, two visible filters (a site chip row and a priority segmented control, never dropdowns),
and the tasks as list rows (icon, the task's name, the trap, why, a Review button); "Review next task" is the one primary. The necropsy task's own
form was built in the 7a language in Phase 4. Local test data only.

The seed has six open tasks across two sites: three at MAN (a High hardware task, a High camera issue, a camera review and a necropsy review) and
two at KAI (a High necropsy review, a camera review)."""
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
TWO_SITES = END_SEED + """
    d = app.load_data()
    kai = d["Traps"][(d["Traps"]["Site ID"] == "KAI") & (d["Traps"]["Status"] == "Active")]["Trap ID"].tolist()
    app.add_followup(d, "Necropsy review", "KAI", kai[0], "V1", "W-K1", "KAI-021", "Dead animal collected", "d", "High")
    app.add_followup(d, "Camera review", "KAI", kai[1], "V1", "W-K2", "", "Trap still set, no animal", "d", "Normal")
    app.save_data(d)
"""
ALL_DONE = END_SEED + """
    d = app.load_data()
    d["Followups"]["Status"] = "Complete"
    app.save_data(d)
"""
ROWS = """() => ({
  stat: (e => e ? [e.innerText, e.nextElementSibling.innerText] : null)(document.querySelector('.st-key-r1_screen .r1-titlerow .r1-stat')),
  rows: [...document.querySelectorAll('[class*="st-key-listrow_"][class*="followup_"]')].map(r => ({
    key: [...r.classList].find(c => c.startsWith('st-key-')), title: r.querySelector('.r1-row-title').innerText, meta: r.querySelector('.r1-meta').innerText,
    tile: r.querySelector('.r1-rowicon').innerHTML.length, button: (b => ({kind: b.getAttribute('kind'), h: Math.round(b.getBoundingClientRect().height)}))(r.querySelector('button'))})),
  primaries: [...document.querySelectorAll('.st-key-r1_screen button[kind="primary"]')].map(b => b.innerText.trim()),
  site: [...document.querySelectorAll('[class*="st-key-chips_followup_site"] button[role="radio"]')].map(b => [b.innerText.trim(), b.getAttribute('aria-checked'), Math.round(b.getBoundingClientRect().height)]),
  priority: [...document.querySelectorAll('[class*="st-key-seg_followup_priority"] button[role="radio"]')].map(b => [b.innerText.trim(), b.getAttribute('aria-checked'), Math.round(b.getBoundingClientRect().height)]),
  body: document.body.innerText,
})"""


def _open(page: Page, url: str) -> None:
    _home(page, url)
    page.get_by_role("link", name=re.compile(r"^Follow-ups")).click()
    expect(page.get_by_role("heading", name="Follow-ups", exact=True)).to_be_visible(timeout=30_000)
    page.wait_for_timeout(1_000)


def test_the_list_is_a_title_with_the_open_count_visible_filters_and_one_row_per_task(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, TWO_SITES) as url:
        _open(page, url)
        v = page.evaluate(ROWS)
        assert v["stat"] == ["6", "Open"], v["stat"]
        # priority first (High, then Normal), then oldest first; the site shows because the list spans two sites
        assert [r["title"] for r in v["rows"]] == ["Trap not ready", "Camera issue", "Necropsy review", "Camera review", "Necropsy review", "Camera review"], v["rows"]
        high = [r for r in v["rows"] if r["meta"].endswith("High priority")]
        assert len(high) == 3 and all(r["meta"].count("Mangaroa Farm") + r["meta"].count("Kaitoke Shed") == 1 for r in v["rows"]), v["rows"]
        assert "listrow_next" in v["rows"][0]["key"] and all("listrow_next" not in r["key"] for r in v["rows"][1:]), "the first row is the one Review next task opens"
        assert any(r["meta"] == "R1-KAI-001 · Kaitoke Shed · Bag KAI-021 · High priority" for r in v["rows"]), "a necropsy shows its bag, not its reason"
        assert all("Normal" not in r["meta"] for r in v["rows"]), "the ordinary priority is not worth saying"
        assert all(r["button"] == {"kind": "secondary", "h": r["button"]["h"]} and r["button"]["h"] >= 44 for r in v["rows"]), "Review is secondary and at least 44px"
        assert v["primaries"] == ["Review next task"], "one primary on the screen"
        assert [s[0] for s in v["site"]] == ["All sites", "Mangaroa Farm", "Kaitoke Shed", "Wairarapa Block"] and v["site"][0][1] == "true"
        assert [s[0] for s in v["priority"]] == ["All", "High", "Normal", "Low"] and v["priority"][0][1] == "true"
        assert all(s[2] >= 44 for s in v["site"] + v["priority"]), "the filters are at least 44px tall"
        for gone in ("Complete tasks created during trap checks", "Review a task directly from its row", "Created:", "Reason:"):
            assert gone not in v["body"], gone


def test_the_filters_narrow_the_list_and_the_site_leaves_the_rows_once_it_is_one_site(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, TWO_SITES) as url:
        _open(page, url)
        page.locator('[class*="st-key-chips_followup_site"] button').filter(has_text="Mangaroa Farm").click()
        expect(page.locator('[class*="st-key-listrow_"][class*="followup_"]')).to_have_count(4, timeout=15_000)
        v = page.evaluate(ROWS)
        assert v["stat"] == ["4", "Open"] and all("Mangaroa" not in r["meta"] for r in v["rows"]), "one site: it is the page's subject, not the rows'"
        page.locator('[class*="st-key-seg_followup_priority"] button').filter(has_text="High").click()
        expect(page.locator('[class*="st-key-listrow_"][class*="followup_"]')).to_have_count(2, timeout=15_000)
        page.locator('[class*="st-key-seg_followup_priority"] button').filter(has_text="Low").click()
        expect(page.get_by_text("No open follow-ups match these filters.", exact=True)).to_be_visible(timeout=15_000)
        assert page.get_by_role("button", name="Review next task").count() == 0
        v = page.evaluate(ROWS)
        assert v["stat"] is None, "a count of 0 would only repeat the panel underneath"
        assert len(v["site"]) == 4 and len(v["priority"]) == 4, "the filters stay, so the operator can change them"


def test_nothing_open_says_so_and_offers_no_next_task(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, ALL_DONE) as url:
        _open(page, url)
        expect(page.get_by_text("All follow-up work is complete.", exact=True)).to_be_visible()
        assert page.get_by_role("button", name="Review next task").count() == 0
        v = page.evaluate(ROWS)
        assert v["stat"] is None, "no count of 0: it would repeat the panel underneath"
        assert v["site"] == [] and v["priority"] == [], "nothing open, so nothing to filter: no chips and no segmented control"


def test_review_opens_that_task_and_review_next_task_opens_the_first(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, TWO_SITES) as url:
        _open(page, url)
        page.locator('[class*="st-key-listrow_"]').filter(has_text="Necropsy review").filter(has_text="Bag KAI-021").get_by_role("button", name="Review", exact=True).click()
        expect(page.get_by_role("heading", name="Necropsy review", exact=True)).to_be_visible(timeout=30_000)
        expect(page.get_by_text("KAI-021", exact=False).first).to_be_visible()
        page.get_by_role("button", name="Back to task list").click()
        expect(page.get_by_role("heading", name="Follow-ups", exact=True)).to_be_visible(timeout=30_000)
        page.get_by_role("button", name="Review next task").click()
        expect(page.get_by_role("heading", name="Trap not ready", exact=True)).to_be_visible(timeout=30_000)


def test_the_trial_hub_opens_the_list_already_filtered_to_its_site(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, TWO_SITES) as url:
        _home(page, url)
        _card(page, "Mangaroa Farm").get_by_role("button", name="Trial overview", exact=True).click()
        expect(page.get_by_text("Evidence waiting", exact=True)).to_be_visible(timeout=30_000)
        page.get_by_role("button", name=re.compile(r"^Open follow-ups for this site")).click()
        expect(page.get_by_role("heading", name="Follow-ups", exact=True)).to_be_visible(timeout=30_000)
        page.wait_for_timeout(1_000)
        v = page.evaluate(ROWS)
        assert [s for s in v["site"] if s[1] == "true"][0][0] == "Mangaroa Farm", v["site"]
        assert v["stat"] == ["4", "Open"], v["stat"]


def test_the_priority_control_is_capped_on_desktop(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(DESKTOP)
    with _serve(data_dir, TWO_SITES) as url:
        _open(page, url)
        width = page.evaluate("document.querySelector('[class*=\"st-key-seg_followup_priority\"] [role=\"radiogroup\"]').getBoundingClientRect().width")
        assert width <= 481, f"a segmented control does not stretch across a desktop: {width}"
