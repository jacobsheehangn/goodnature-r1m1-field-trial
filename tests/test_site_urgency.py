"""Boundary-condition tests for site_urgency_pill (card-system brief Phase 2).

app.py can't be imported directly — it runs the whole app at module level
(st.set_page_config, page routing, etc.) with no guard for a plain import.
site_urgency_pill itself is a pure function with no dependency on anything
else in the file (no globals, no Streamlit calls), so its exact source is
extracted via ast and exec'd in isolation — this tests the real
implementation, not a re-typed copy that could silently drift from it.
"""
from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path

import pytest

APP_SOURCE = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")


def _load_site_urgency_pill():
    tree = ast.parse(APP_SOURCE)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "site_urgency_pill":
            segment = ast.get_source_segment(APP_SOURCE, node)
            namespace: dict = {}
            exec(segment, namespace)
            return namespace["site_urgency_pill"]
    raise AssertionError("site_urgency_pill not found in app.py — has it been renamed or moved?")


site_urgency_pill = _load_site_urgency_pill()

TODAY = date(2026, 8, 15)


def test_far_in_the_future_shows_no_pill():
    text, kind = site_urgency_pill(TODAY + timedelta(days=10), TODAY)
    assert (text, kind) == ("", "none")


def test_due_tomorrow_still_shows_no_pill():
    # Not "due soon" by this brief's definition — quiet until it's actually today or overdue.
    text, kind = site_urgency_pill(TODAY + timedelta(days=1), TODAY)
    assert (text, kind) == ("", "none")


def test_exactly_due_today():
    text, kind = site_urgency_pill(TODAY, TODAY)
    assert text == "Due today"
    assert kind == "warning"


def test_one_day_overdue_singular():
    text, kind = site_urgency_pill(TODAY - timedelta(days=1), TODAY)
    assert text == "Overdue by 1 day"
    assert kind == "error"


def test_multiple_days_overdue_plural():
    text, kind = site_urgency_pill(TODAY - timedelta(days=5), TODAY)
    assert text == "Overdue by 5 days"
    assert kind == "error"


def test_far_overdue():
    text, kind = site_urgency_pill(TODAY - timedelta(days=42), TODAY)
    assert text == "Overdue by 42 days"
    assert kind == "error"


@pytest.mark.parametrize("offset,expected_kind", [(-1, "error"), (0, "warning"), (1, "none")])
def test_boundary_sweep_around_today(offset, expected_kind):
    """The three cases that actually matter sit right next to each other —
    exercise all three in one sweep so a future off-by-one regression can't
    slip through by only checking cases far from the boundary."""
    _, kind = site_urgency_pill(TODAY + timedelta(days=offset), TODAY)
    assert kind == expected_kind
