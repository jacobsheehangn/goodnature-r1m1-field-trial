"""Records a deliberate change in the photo chain on top of the golden frozen from main (see record_deliberate_changes.py).

    R1M1_ENVIRONMENT=local R1M1_ALLOW_NO_AUTH=true R1M1_SEED_MODE=clean R1M1_DATA_DIR=$(mktemp -d) \\
        PYTHONPATH=.:tests python tests/golden/record_deliberate_photo_changes.py --reason "<why>"

Runs the photo-chain cases through app.build_check_records() and commit_staged_records_with_photos(), and writes the cases that differ
from the frozen golden (check_save_golden_photos.json) to check_save_golden_photos_changes.json. The frozen golden is not edited."""
import argparse, json, sys

import app
import check_save_matrix as m

parser = argparse.ArgumentParser()
parser.add_argument("--reason", required=True)
args = parser.parse_args()
frozen = json.loads((m.GOLDEN_DIR / "check_save_golden_photos.json").read_text(encoding="utf-8"))["cases"]
new = m.compute_photo_chain(app, "extracted")
moved = {case: new[case] for case in frozen if new[case] != frozen[case]}
if not moved:
    sys.exit("No photo-chain case differs from the frozen golden; nothing to record.")
(m.GOLDEN_DIR / "check_save_golden_photos_changes.json").write_text(
    json.dumps({"reason": args.reason, "cases": moved}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print("recorded:", ", ".join(moved))
