"""Records a deliberate change in what Save check writes, on top of the golden frozen from main, without touching that golden.

Run from the repo root, against the code that has the deliberate change:
    R1M1_ENVIRONMENT=local R1M1_ALLOW_NO_AUTH=true R1M1_SEED_MODE=clean R1M1_DATA_DIR=$(mktemp -d) \\
        PYTHONPATH=.:tests python tests/golden/record_deliberate_changes.py --reason "<why>"

It runs the matrix through app.build_check_records(), finds the cells whose rows differ from the frozen golden, and writes exactly those
cells (their new digest and full new rows) to check_save_golden_changes.json. tests/test_check_save_golden.py then holds the function to
the frozen golden overlaid with these changes, and states which cells are allowed to move. The frozen golden is never edited.
"""
import argparse, json, sys

import app
import check_save_matrix as m

parser = argparse.ArgumentParser()
parser.add_argument("--reason", required=True)
args = parser.parse_args()

base = {}
for line in (m.GOLDEN_DIR / "check_save_golden_digests.tsv").read_text(encoding="utf-8").splitlines():
    if line and not line.startswith("#"):
        key, value = line.rsplit("\t", 1)
        base[key] = value
new = m.compute(app, "extracted")["digests"]
moved = [key for key in base if new[key] != base[key]]
if not moved:
    sys.exit("No cell differs from the frozen golden; nothing to record.")
by_key = {m.cell_key(c): c for c in m.cells()}
rows = m.compute(app, "extracted", keep_rows_for=lambda c: m.cell_key(c) in set(moved))["rows"]
out = {"reason": args.reason, "cells": {key: {"digest": new[key], "rows": rows[key]} for key in moved}}
(m.GOLDEN_DIR / "check_save_golden_changes.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print(f"recorded {len(moved)} changed cells:")
for key in moved:
    print("  ", key)
