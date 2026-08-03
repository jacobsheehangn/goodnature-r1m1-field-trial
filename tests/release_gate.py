from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

from artifact_tool import Blob, SpreadsheetFile

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
CLEAN = ROOT / "field_trial_data_clean_seed.xlsx"

results: list[dict] = []

def check(name: str, passed: bool, detail: str = "") -> None:
    results.append({"check": name, "passed": bool(passed), "detail": detail})

source = APP.read_text(encoding="utf-8")

try:
    ast.parse(source)
    check("Python syntax", True)
except SyntaxError as exc:
    check("Python syntax", False, str(exc))

banned = {
    "Embedded camera removed": "st.camera_input(",
    "Old route wording removed": "Route point ",
    "Zoom remains enabled": "user-scalable=no",
    "No maximum scale lock": "maximum-scale",
    "No sticky CTA selector": ".element-container:has(.mobile-save-anchor)",
}
for name, token in banned.items():
    check(name, token not in source, f"Forbidden token: {token}")

required = {
    "Upload-only photo picker": "st.file_uploader(",
    "Multiple image upload": "accept_multiple_files=True",
    "Top-reset navigation": "st.session_state.scroll_to_top_once = True",
    "Delayed scroll retries": "[80, 200, 450, 900]",
    "Card wrapper": "def app_card():",
    "Safe-area handling": "env(safe-area-inset-bottom)",
    "Mobile 16px inputs": "font-size: 16px !important",
    "Radio styling": 'label[data-baseweb="radio"]',
    "Checkbox styling": 'label[data-baseweb="checkbox"]',
    "Sidebar chevron styling": 'aria-label*="sidebar" i',
}
for name, token in required.items():
    check(name, token in source, f"Required token: {token}")

wb = SpreadsheetFile.import_xlsx(Blob.load(str(CLEAN)))
sheets = ["Sites","Builds","Traps","Visits","Checks","Windows","Followups","Audit Log","Photos"]
data = {}
for sheet_name in sheets:
    ws = wb.worksheets.get_item(sheet_name)
    values = ws.get_range("A1:AZ1000").values
    headers = [str(v) if v is not None else "" for v in values[0]]
    rows = []
    for row in values[1:]:
        if any(v not in (None, "") for v in row):
            padded = list(row) + [None] * max(0, len(headers) - len(row))
            rows.append(dict(zip(headers, padded[:len(headers)])))
    data[sheet_name] = rows

expected_counts = {
    "Sites": 3, "Traps": 15, "Visits": 0, "Checks": 0,
    "Windows": 15, "Followups": 0, "Audit Log": 0, "Photos": 0
}
actual_counts = {name: len(data[name]) for name in expected_counts}
check("Clean seed counts", actual_counts == expected_counts, json.dumps(actual_counts))

def values(rows, key):
    return [str(r.get(key)) for r in rows if r.get(key) not in (None, "")]

def duplicates(items):
    return sorted([k for k, v in Counter(items).items() if v > 1])

for sheet_name, key in [("Sites","Site ID"),("Traps","Trap ID"),("Windows","Window ID")]:
    dups = duplicates(values(data[sheet_name], key))
    check(f"Unique {sheet_name} IDs", not dups, json.dumps(dups))

site_ids = set(values(data["Sites"], "Site ID"))
trap_ids = set(values(data["Traps"], "Trap ID"))
broken = []
for row in data["Traps"]:
    if str(row.get("Site ID")) not in site_ids:
        broken.append(f"Trap {row.get('Trap ID')} → {row.get('Site ID')}")
for row in data["Windows"]:
    if str(row.get("Site ID")) not in site_ids:
        broken.append(f"Window {row.get('Window ID')} site")
    if str(row.get("Trap ID")) not in trap_ids:
        broken.append(f"Window {row.get('Window ID')} trap")
check("Workbook references", not broken, json.dumps(broken))

open_counts = Counter(
    str(row.get("Trap ID"))
    for row in data["Windows"]
    if str(row.get("Status")) == "Open"
)
bad_open = {tid: open_counts.get(tid, 0) for tid in trap_ids if open_counts.get(tid, 0) != 1}
check("One open window per trap", not bad_open, json.dumps(bad_open))

error_scan = wb.inspect({
    "kind": "match",
    "search_term": "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    "options": {"use_regex": True, "max_results": 300},
    "summary": "release gate formula scan",
}).ndjson
no_formula_errors = (
    "matched 0 entries" in error_scan
    or '"count":0' in error_scan
    or '"matches":[]' in error_scan
)
check("Workbook formula errors", no_formula_errors, error_scan[:500])

failed = [item for item in results if not item["passed"]]
print(json.dumps({
    "passed": not failed,
    "checks": results,
    "failed_count": len(failed),
}, indent=2))
sys.exit(1 if failed else 0)
