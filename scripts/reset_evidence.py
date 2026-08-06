from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
evidence = root / "evidence"
for name in ["screenshots", "traces", "videos"]:
    path = evidence / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
for name in ["gate-results.json", "gate-report.md", "browser-junit.xml", "code-data-gate.json"]:
    path = evidence / name
    if path.exists():
        path.unlink()
