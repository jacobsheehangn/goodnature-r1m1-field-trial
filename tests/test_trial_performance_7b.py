"""Phase 7b, Trial performance (TrialPerformance board): a title, the filters in a card, and three summary cards in the 7a language: Kill outcome (two big numbers,
what the rate is based on, a warning panel for kills awaiting assessment, an info panel for kills not assessed), Time to kill, and Evidence (camera reviews complete,
unresolved). Headings and messages further down are in the same language. The camera funnel's visuals and logic are untouched, and so is every figure. Local test data only.

The seed: 17 kills (12 humane, 2 not, 1 awaiting final assessment, 1 no carcass, 1 trial ended), the first six with usable timing (95 minutes), 13 camera windows
of which 12 are complete and 1 unresolved."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from test_trial_model_ui import _serve  # noqa: E402
from test_trial_screens import _choose  # noqa: E402

PHONE, DESKTOP = {"width": 414, "height": 896}, {"width": 1280, "height": 900}
SEED = """
    import app, pandas as pd
    data = app.create_sample_data()
    trap = data["Traps"][data["Traps"]["Product"] == "R1"].iloc[0]
    def window(wid, final, finding="Dead animal found", camera="No", review="Complete"):
        row = {c: "" for c in app.SHEETS["Windows"]}
        row.update({"Window ID": wid, "Trap ID": trap["Trap ID"], "Product": trap["Product"], "Build Version": trap["Build Version"], "Site ID": trap["Site ID"], "Status": "Closed",
                    "Start Time": "2026-08-01 00:00:00", "End Time": "2026-08-02 00:00:00", "Finding At Close": finding, "Camera Assigned": camera, "Final Humane Kill": final, "Review Status": review})
        return row
    rows = [window(f"K-YES-{i}", "Yes", camera="Yes") for i in range(12)] + [window(f"K-NO-{i}", "No") for i in range(2)] + [window("K-WAIT", "Pending")]
    rows += [window("K-NOCARCASS", app.NOT_ASSESSED_NO_CARCASS), window("K-ENDED", app.NOT_ASSESSED_TRIAL_ENDED), window("CAM-UNRESOLVED", "", finding="Trap still set, no animal", camera="Yes", review="Unresolved")]
    for r in rows[:6]:
        r.update({"Evidence Usable": "Yes", "Target Present": "Yes", "Entered Strike Area": "Yes", "Trap Activated": "Yes", "Kill Confirmed": "Yes", "Interaction To Kill Min": "95"})
    data["Windows"] = pd.concat([data["Windows"], pd.DataFrame(rows)], ignore_index=True)
    app.save_data(data)
"""
VIEW = """() => {
  const text = e => e ? e.innerText.replace(/\\s+/g, ' ').trim() : null;
  const card = k => document.querySelector('[class*="st-key-card_perf_' + k + '"]');
  const top = k => Math.round(card(k).getBoundingClientRect().top);
  return {
    title: text(document.querySelector('.st-key-r1_screen .r1-title')),
    kill: {title: text(card('kill').querySelector('.r1-card-title')), stats: [...card('kill').querySelectorAll('.r1-stats2 > div')].map(text),
           meta: text(card('kill').querySelector('.r1-meta')), warn: text(card('kill').querySelector('.r1-msg.warn')), info: text(card('kill').querySelector('.r1-msg.info'))},
    time: {title: text(card('time').querySelector('.r1-card-title')), stats: [...card('time').querySelectorAll('.r1-stats2 > div')].map(text), meta: [...card('time').querySelectorAll('.r1-meta')].map(text)},
    evidence: {title: text(card('evidence').querySelector('.r1-card-title')), rows: [...card('evidence').querySelectorAll('.r1-kv')].map(text), meta: [...card('evidence').querySelectorAll('.r1-meta')].map(text)},
    tops: [top('kill'), top('time'), top('evidence')],
    sections: [...document.querySelectorAll('.r1-section[role="heading"]')].map(e => [text(e), e.getAttribute('aria-level')]),
    attention: text(document.querySelector('.st-key-r1_screen .r1-msg.warn:not([class*="x"]) ~ *')) ,
    funnelRows: document.querySelectorAll('.funnel-row').length,
    navigation: document.querySelectorAll('.st-key-nav_desktop, .st-key-nav_phone').length,
    body: document.body.innerText,
  }; }"""


def _open(page: Page, url: str, phone: bool) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.get_by_text("Trap sites", exact=True).last).to_be_visible(timeout=30_000)
    page.wait_for_timeout(1_000)
    if phone:
        page.get_by_role("button", name="More", exact=True).click()
    page.get_by_role("link", name="Trial performance", exact=True).click()
    expect(page.get_by_role("heading", name="Trial performance", exact=True)).to_be_visible(timeout=30_000)
    page.wait_for_timeout(1_000)
    _choose(page, "Trap type", "R1")
    expect(page.get_by_text("Kill outcome", exact=True)).to_be_visible(timeout=30_000)
    page.wait_for_timeout(1_500)


def test_the_three_summary_cards_follow_the_board_and_say_the_same_facts(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(PHONE)
    with _serve(data_dir, SEED) as url:
        _open(page, url, phone=True)
        v = page.evaluate(VIEW)
        assert v["title"] == "Trial performance"
        k = v["kill"]
        assert k["title"] == "Kill outcome" and k["stats"] == ["12 good kills", "86% humane"], k
        assert k["meta"] == "Based on 14 assessed kills of 17.", k["meta"]
        assert k["warn"] == "1 kill awaiting final assessment — see Results needing attention", k["warn"]
        assert k["info"] == "2 kills not assessed (1 no carcass, 1 trial ended).", k["info"]
        t = v["time"]
        assert t["title"] == "Time to kill" and t["stats"] == ["6 of 6 Met <24 hr target"] and t["meta"] == ["Median: 1.6 hr", "6 of 17 total kills have usable timing"], t
        e = v["evidence"]
        assert e["title"] == "Evidence" and e["rows"] == ["Camera reviews complete 12 of 13", "Unresolved 1"], e
        assert e["meta"] == ["Unresolved = review given up on at trial end. Not counted as complete."], e["meta"]
        for gone in ("Necropsy-dependent", "Camera-dependent", "Coverage card", "Kill assessments complete", "→ ", "Open camera reviews:", "Unusable footage:", "All 17 count as kills"):
            assert gone not in v["body"], f"{gone!r} should be gone"


def test_the_cards_stack_on_a_phone_and_sit_side_by_side_on_desktop(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, SEED) as url:
        page.set_viewport_size(PHONE)
        _open(page, url, phone=True)
        a, b, c = page.evaluate(VIEW)["tops"]
        assert a < b < c, f"stacked on a phone: {a, b, c}"
        page.set_viewport_size(DESKTOP); page.wait_for_timeout(1_000)
        a, b, c = page.evaluate(VIEW)["tops"]
        assert a == b == c, f"three across on desktop: {a, b, c}"


def test_the_headings_and_messages_below_the_cards_are_in_the_same_language_and_the_funnel_is_untouched(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(DESKTOP)
    with _serve(data_dir, SEED) as url:
        _open(page, url, phone=False)
        v = page.evaluate(VIEW)
        assert v["sections"] == [["Camera conversion funnel", "2"], ["What is driving the result?", "2"], ["Results needing attention", "2"]], v["sections"]
        expect(page.locator(".r1-msg.warn").filter(has_text="2 bad kills · 7 incomplete results")).to_be_visible()
        assert v["funnelRows"] == 5, "the camera funnel keeps its five stages, drawn as before"
        assert v["navigation"] >= 1, "the navigation stays on this page"
        # the breakdown control still works and the figures it reads are unchanged
        _choose(page, "Break down performance by", "Rat type")
        expect(page.get_by_role("combobox", name="Break down performance by")).to_have_value("Rat type", timeout=15_000)
        expect(page.get_by_text("0 of 17 windows have necropsy-confirmed species.", exact=False)).to_be_visible(timeout=15_000)


def test_combining_builds_warns_in_a_message_panel(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    page.set_viewport_size(DESKTOP)
    with _serve(data_dir, SEED) as url:
        _open(page, url, phone=False)
        _choose(page, "Build to assess", "All builds — use with care")
        expect(page.locator(".r1-msg.warn").filter(has_text="These results combine different builds. Use them for exploration, not a single performance conclusion.")).to_be_visible(timeout=15_000)
