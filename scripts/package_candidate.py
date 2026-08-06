from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
results_path = ROOT / "evidence" / "gate-results.json"
if not results_path.exists():
    raise SystemExit("Release blocked: missing evidence/gate-results.json")
results = json.loads(results_path.read_text())
required = ["code_data_gate", "browser_gate", "visual_evidence_gate"]
failed = [key for key in required if results.get(key, {}).get("status") != "PASS"]
if failed:
    raise SystemExit("Release blocked: mandatory gates not passed: " + ", ".join(failed))

dist = ROOT / "dist"
if dist.exists():
    shutil.rmtree(dist)
dist.mkdir()
zip_path = dist / "R1_M1_Field_Trial_App_verified_candidate.zip"
exclude_roots = {"dist", ".git", "__pycache__"}
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if rel.parts and rel.parts[0] in exclude_roots:
            continue
        if "__pycache__" in rel.parts or path.suffix == ".pyc":
            continue
        archive.write(path, arcname=f"R1_M1_Field_Trial_App/{rel}")
with zipfile.ZipFile(zip_path) as archive:
    bad = archive.testzip()
    if bad:
        raise SystemExit(f"Release blocked: corrupt ZIP member {bad}")
print(zip_path)
