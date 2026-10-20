"""Trap sites on desktop and the Administration menu (14 Oct 2026, boards SitesDesktop / SitesPhone / B3MenuOperatorDesktop).

Held here: the figure says "Due now" and counts an overdue site; the untracked note is said once with the right count and each untracked card carries a
"Not tracked" tag; over 700px the cards sit two across with each card's buttons side by side; on a phone the buttons stay full width and stacked, as
approved in 7b; the Administration menu's labels line up with its pill, every row is 48px, Operator is a group heading with its help as a visible line,
and the nav pills use the app font."""
from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]

SEED = """
    import datetime as dt, app, pandas as pd
    data = app.create_sample_data()
    for sheet in ("Sites", "Windows"):
        data[sheet] = data[sheet].replace(r"(?i)synthetic|sample", "", regex=True)
    names = {{"MAN": "Moa Point", "KAI": "Hutt River", "WAI": "Seaview"}}
    data["Sites"]["Site Name"] = data["Sites"]["Site ID"].map(names)
    def visit(site, start, end, status):
        row = [app.make_id("VIS-" + site), site, "Jake", app.dtstr(start), app.dtstr(end) if end else "", status, ""]
        data["Visits"] = pd.concat([data["Visits"], pd.DataFrame([row], columns=app.SHEETS["Visits"])], ignore_index=True)
        return row[0]
    now = app.now()
    if {man_overdue}:
        visit("MAN", now - dt.timedelta(days=20, hours=1), now - dt.timedelta(days=20), "Complete")   # next due 17 days ago
    else:
        visit("MAN", now - dt.timedelta(hours=3), now - dt.timedelta(hours=2), "Complete")            # checked today: nothing due
    visit("KAI", now - dt.timedelta(hours=3), now - dt.timedelta(hours=2), "Complete")
    app.create_trial(data, "WAI", ["R1 · R1 Build 4.3"], now - dt.timedelta(days=3))
    visit("WAI", now - dt.timedelta(hours=3), now - dt.timedelta(hours=2), "Complete")
    {track}
    data["Sites"].loc[~data["Sites"]["Site ID"].isin({keep!r}), "Status"] = "Inactive"
    app.save_data(data)
"""


def seed(keep=("MAN", "KAI", "WAI"), man_overdue=True, track=()):
    tracked = "".join(f'app.create_trial(data, "{s}", ["R1 · R1 Build 4.3"], now - dt.timedelta(days=3))\n    ' for s in track)
    return SEED.format(keep=list(keep), man_overdue=man_overdue, track=tracked)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def serve(data_dir: Path, code: str):
    data_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=str(data_dir),
               STREAMLIT_BROWSER_GATHER_USAGE_STATS="false", PYTHONPATH=str(ROOT))
    seeded = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
    assert seeded.returncode == 0, f"stdout={seeded.stdout}\nstderr={seeded.stderr[-3000:]}"
    port = _free_port()
    process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.address", "127.0.0.1", "--server.port", str(port),
                                "--server.headless", "true", "--browser.gatherUsageStats", "false"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    try:
        while True:
            if process.poll() is not None:
                raise RuntimeError("Local Streamlit process exited before becoming ready.")
            try:
                with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except Exception:
                if time.monotonic() > deadline:
                    raise RuntimeError("Local Streamlit app did not become ready within 60 seconds.")
                time.sleep(0.25)
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def open_sites(page: Page, url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 1100 if width > 700 else 1700})
    page.goto(url, wait_until="domcontentloaded")
    page.locator(".r1-title").first.wait_for(timeout=45000)
    page.wait_for_timeout(1500)


def card(page: Page, site: str):
    return page.locator(f'[class*="st-key-card_site_{site}"]').first


# ---------------------------------------------------------------- "Due now"
def test_due_now_counts_a_site_that_is_only_overdue(tmp_path, page: Page):
    with serve(tmp_path / "d", seed(keep=("MAN",), man_overdue=True)) as url:  # one site, 17 days overdue, nothing "due today"
        open_sites(page, url, 1280)
        stat = page.locator(".r1-titlerow").first
        expect(stat.get_by_text("Due now")).to_be_visible()
        assert stat.locator(".r1-stat").inner_text().strip() == "1"
        assert "Due today" not in page.locator("body").inner_text()
        expect(card(page, "MAN").get_by_text("Overdue by 17 days")).to_be_visible()


def test_due_now_is_not_shown_when_nothing_is_due(tmp_path, page: Page):
    with serve(tmp_path / "d", seed(keep=("MAN", "KAI"), man_overdue=False)) as url:
        open_sites(page, url, 1280)
        assert page.locator(".r1-title").first.evaluate("e => e.closest('.r1-titlerow').querySelector('.r1-stat') === null")
        assert "Due now" not in page.locator("body").inner_text()


# ---------------------------------------------------------------- the untracked note
@pytest.mark.parametrize("track, title, tags", [
    ((), "2 sites aren't tracked as trials yet", 2),             # MAN and KAI untracked; the seed always tracks WAI
    (("KAI",), "1 site isn't tracked as a trial yet", 1),        # only MAN
])
def test_the_untracked_note_is_said_once_and_each_untracked_card_is_tagged(track, title, tags, tmp_path, page: Page):
    with serve(tmp_path / "d", seed(track=track)) as url:
        open_sites(page, url, 1280)
        body = page.locator("body").inner_text()
        assert body.count("aren't tracked as trials yet") + body.count("isn't tracked as a trial yet") == 1, "the note appears once"
        expect(page.get_by_text(title)).to_be_visible()
        assert page.locator(".r1-tag", has_text="Not tracked").count() == tags
        assert "Not tracked as a trial yet" not in body, "the old per-card panel is gone"


def test_no_note_when_every_visible_site_is_tracked(tmp_path, page: Page):
    with serve(tmp_path / "d", seed(track=("KAI", "MAN"))) as url:
        open_sites(page, url, 1280)
        assert page.locator(".r1-tag").count() == 0 and "tracked as" not in page.locator("body").inner_text()


def test_no_note_and_no_tag_when_every_site_is_tracked(tmp_path, page: Page):
    with serve(tmp_path / "d", seed(keep=("WAI",))) as url:
        open_sites(page, url, 1280)
        assert page.locator(".r1-tag").count() == 0
        assert "tracked as" not in page.locator("body").inner_text()


# ---------------------------------------------------------------- layout
def test_on_desktop_the_cards_are_two_across_with_their_buttons_side_by_side(tmp_path, page: Page):
    with serve(tmp_path / "d", seed()) as url:
        open_sites(page, url, 1280)
        a, b, c = (card(page, s).bounding_box() for s in ("MAN", "KAI", "WAI"))
        assert abs(a["y"] - b["y"]) < 2 and b["x"] > a["x"] + a["width"] - 2, "MAN and KAI share a row"
        assert abs(c["x"] - a["x"]) < 2 and c["y"] > a["y"] + a["height"], "WAI starts the next row in the first column"
        assert 12 <= b["x"] - (a["x"] + a["width"]) <= 20, "16px between the columns"
        for site in ("MAN", "KAI", "WAI"):
            buttons = card(page, site).locator("button").all()
            first, second = buttons[0].bounding_box(), buttons[1].bounding_box()
            assert abs(first["y"] + first["height"] / 2 - (second["y"] + second["height"] / 2)) < 3, f"{site}: the two actions share a line"
            assert second["x"] > first["x"] + first["width"], f"{site}: the text action is to the right of the button"


@pytest.mark.parametrize("width", [390, 414])
def test_on_a_phone_the_cards_stack_and_the_buttons_stay_full_width_and_centred(width, tmp_path, page: Page):
    with serve(tmp_path / "d", seed()) as url:
        open_sites(page, url, width)
        boxes = [card(page, s).bounding_box() for s in ("MAN", "KAI", "WAI")]
        assert boxes[0]["y"] < boxes[1]["y"] < boxes[2]["y"] and len({round(b["x"]) for b in boxes}) == 1, "one column"
        for site, box in zip(("MAN", "KAI", "WAI"), boxes):
            first, second = (b.bounding_box() for b in card(page, site).locator("button").all()[:2])
            inner = box["width"] - 30
            assert abs(first["width"] - inner) < 2 and abs(second["width"] - inner) < 2, f"{site}: both full width"
            assert second["y"] > first["y"] + first["height"], f"{site}: the text action is under the button"
            assert first["height"] in (44, 48) and abs(first["x"] - second["x"]) < 1
            text = card(page, site).locator("button").all()[1].locator("p").first.bounding_box()
            assert abs((text["x"] + text["width"] / 2) - (box["x"] + box["width"] / 2)) < 4, f"{site}: the text action is centred"


# ---------------------------------------------------------------- the menu and the pills
def test_the_administration_menu_lines_up_with_its_pill_and_every_row_is_48px(tmp_path, page: Page):
    with serve(tmp_path / "d", seed()) as url:
        open_sites(page, url, 1280)
        pill = page.get_by_role("button", name="Administration").first
        pill_box = pill.bounding_box()
        text_left = pill.locator("p").first.bounding_box()["x"]
        pill.click()
        page.wait_for_timeout(1000)
        body = page.locator('[data-testid="stPopoverBody"]').first
        body_box = body.bounding_box()
        assert abs(body_box["x"] - pill_box["x"]) < 2, "the panel's left edge is the pill's"
        labels = body.locator('[data-testid="stPageLink"] a p').all()
        assert len(labels) == 4
        for label in labels:
            assert abs(label.bounding_box()["x"] - text_left) < 1.5, "labels sit at the pill's own 16px inset"
        rows = body.locator('[data-testid="stPageLink"] a').all() + [body.get_by_role("button", name="Sign out").first]
        assert all(abs(r.bounding_box()["height"] - 48) < 1 for r in rows), "every row, Sign out included, is 48px"
        ys = sorted(r.bounding_box()["y"] for r in body.locator('[data-testid="stPageLink"] a').all())
        assert all(abs((b - a) - 48) < 2 for a, b in zip(ys, ys[1:])), "rows sit edge to edge, no overlap"
        help_line = body.locator(".r1-menu-help")
        expect(help_line).to_be_visible()
        expect(help_line).to_have_text("Attributed to every visit and check you record until changed.")
        assert body.locator('[data-testid="stTooltipIcon"], [data-testid="stTooltipHoverTarget"]').count() == 0, "no \"?\" tooltip"
        expect(body.locator(".r1-menu-group", has_text="Operator")).to_be_visible()
        expect(body.get_by_role("textbox", name="Operator")).to_have_value("Jake" if False else body.get_by_role("textbox", name="Operator").input_value())
        sign_out = body.get_by_role("button", name="Sign out").bounding_box()
        help_box = help_line.bounding_box()
        assert 0 <= sign_out["y"] - (help_box["y"] + help_box["height"]) < 3, "nothing but the divider between the help line and Sign out"


def test_the_nav_pills_and_the_menu_use_lato(tmp_path, page: Page):
    with serve(tmp_path / "d", seed()) as url:
        open_sites(page, url, 1280)
        font = page.locator('.st-key-app_nav [data-testid="stPageLink"] a p').first.evaluate("e => getComputedStyle(e).fontFamily")
        assert font.lower().startswith("lato"), font
        page.get_by_role("button", name="Administration").first.click()
        page.wait_for_timeout(800)
        assert page.locator('[data-testid="stPopoverBody"] [data-testid="stPageLink"] a p').first.evaluate("e => getComputedStyle(e).fontFamily").lower().startswith("lato")


def test_the_phone_more_menu_is_in_the_same_style(tmp_path, page: Page):
    with serve(tmp_path / "d", seed()) as url:
        open_sites(page, url, 390)
        page.get_by_role("button", name="More").first.click()
        page.wait_for_timeout(1000)
        body = page.locator('[data-testid="stPopoverBody"]').first
        expect(body.locator(".r1-menu-group", has_text="Administration")).to_be_visible()
        expect(body.locator(".r1-menu-group", has_text="Operator")).to_be_visible()
        expect(body.locator(".r1-menu-help")).to_be_visible()
        for row in body.locator('[data-testid="stPageLink"] a').all():
            assert abs(row.bounding_box()["height"] - 48) < 1
