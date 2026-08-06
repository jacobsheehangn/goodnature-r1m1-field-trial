from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"


def parse_code_data() -> dict:
    path = EVIDENCE / "code-data-gate.json"
    if not path.exists():
        return {"status": "FAIL", "detail": "Missing code/data gate output"}
    try:
        payload = json.loads(path.read_text())
        return {
            "status": "PASS" if payload.get("passed") else "FAIL",
            "detail": f"{len(payload.get('checks', []))} checks; {payload.get('failed_count', 0)} failed",
        }
    except Exception as exc:
        return {"status": "FAIL", "detail": f"Unreadable code/data gate output: {exc}"}


def parse_browser() -> dict:
    path = EVIDENCE / "browser-junit.xml"
    if not path.exists():
        return {"status": "FAIL", "detail": "Missing browser JUnit output"}
    try:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
        failures = sum(int(suite.attrib.get("failures", 0)) for suite in suites)
        errors = sum(int(suite.attrib.get("errors", 0)) for suite in suites)
        skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
        status = "PASS" if tests > 0 and failures == 0 and errors == 0 and skipped == 0 else "FAIL"
        return {"status": status, "detail": f"{tests} tests; {failures} failures; {errors} errors; {skipped} skipped"}
    except Exception as exc:
        return {"status": "FAIL", "detail": f"Unreadable browser JUnit output: {exc}"}


required_shots = [
    "mobile_390_home.png",
    "mobile_430_home.png",
    "desktop_1440_home.png",
    "mobile_partial_visit.png",
    "mobile_checked_state.png",
    "mobile_all_traps_checked.png",
    "mobile_photo_queue_ready.png",
    "mobile_photo_queue_processed.png",
    "mobile_move_trap_open.png",
    "desktop_data_records.png",
]

code_data = parse_code_data()
browser = parse_browser()
missing = [name for name in required_shots if not (EVIDENCE / "screenshots" / name).exists()]
visual = {
    "status": "PASS" if not missing else "FAIL",
    "detail": "Required screenshots present" if not missing else "Missing: " + ", ".join(missing),
}

results = {
    "implemented": "YES",
    "code_data_gate": code_data,
    "browser_gate": browser,
    "visual_evidence_gate": visual,
    "live_staging_gate": {"status": "NOT_RUN", "detail": "Runs only after mandatory local gates pass"},
    "field_approval": "NO",
    "required_screenshots": required_shots,
    "missing_screenshots": missing,
}
(EVIDENCE / "gate-results.json").write_text(json.dumps(results, indent=2))

lines = [
    "# R1/M1 Release Gate Report",
    "",
    f"- Code and fixture data: **{code_data['status']}** — {code_data['detail']}",
    f"- Browser workflows: **{browser['status']}** — {browser['detail']}",
    f"- Visual evidence present: **{visual['status']}** — {visual['detail']}",
    "- Live staging: **NOT RUN** until mandatory local gates pass",
    "- Field approval: **NO**",
]
(EVIDENCE / "gate-report.md").write_text("\n".join(lines) + "\n")
print(json.dumps(results, indent=2))
