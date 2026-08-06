from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "evidence" / "gate-results.json"
if not path.exists():
    raise SystemExit("FAIL: evidence/gate-results.json does not exist")
results = json.loads(path.read_text())
failed = []
for key in ["code_data_gate", "browser_gate", "visual_evidence_gate"]:
    if results.get(key, {}).get("status") != "PASS":
        failed.append(f"{key}: {results.get(key)}")
if failed:
    raise SystemExit("RELEASE BLOCKED\n" + "\n".join(failed))
print("MANDATORY LOCAL RELEASE GATES PASSED")
