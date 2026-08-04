from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

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

wb = load_workbook(CLEAN, data_only=False, read_only=True)
sheets = ["Sites","Builds","Traps","Visits","Checks","Windows","Followups","Audit Log","Photos"]
data = {}

missing_sheets = [name for name in sheets if name not in wb.sheetnames]
check("Required workbook sheets", not missing_sheets, json.dumps(missing_sheets))

for sheet_name in sheets:
    if sheet_name not in wb.sheetnames:
        data[sheet_name] = []
        continue
    ws = wb[sheet_name]
    values = list(ws.iter_rows(min_row=1, max_row=1000, max_col=52, values_only=True))
    if not values:
        data[sheet_name] = []
        continue
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

formula_errors = []
error_pattern = re.compile(r"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A")
for ws in wb.worksheets:
    for row in ws.iter_rows():
        for cell in row:
            value = cell.value
            if isinstance(value, str) and error_pattern.search(value):
                formula_errors.append(f"{ws.title}!{cell.coordinate}: {value}")
                if len(formula_errors) >= 300:
                    break
        if len(formula_errors) >= 300:
            break
    if len(formula_errors) >= 300:
        break
check("Workbook formula errors", not formula_errors, json.dumps(formula_errors[:20]))

failed = [item for item in results if not item["passed"]]
print(json.dumps({
    "passed": not failed,
    "checks": results,
    "failed_count": len(failed),
}, indent=2))
sys.exit(1 if failed else 0)


# v8.6.53 architecture markers
