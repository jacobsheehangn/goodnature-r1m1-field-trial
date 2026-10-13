"""Freezes the golden record for Save check: what the check page writes, for every cell of tests/check_save_matrix.py.

Run from the repo root with a throwaway data dir, against the code to be frozen:
    R1M1_ENVIRONMENT=local R1M1_ALLOW_NO_AUTH=true R1M1_SEED_MODE=clean R1M1_DATA_DIR=$(mktemp -d) \\
        PYTHONPATH=.:tests python tests/golden/freeze_check_save.py --from-commit <sha>

It runs the frozen inline block (tests/golden/check_save_inline_block_main.txt, the page's code as it stood on main), never the
extracted function: the golden is today's behaviour, not whatever the new code does. It refuses to overwrite an existing golden
unless --deliberate "<why>" is given, and records the reason in the file. The golden is never edited to make a test pass.
"""
import argparse, json, sys
from pathlib import Path

import app
import check_save_matrix as m

parser = argparse.ArgumentParser()
parser.add_argument("--from-commit", required=True, help="the commit whose behaviour is being frozen")
parser.add_argument("--deliberate", default="", help="why an existing golden is being replaced (a reviewed behaviour change)")
args = parser.parse_args()

digests_path = m.GOLDEN_DIR / "check_save_golden_digests.tsv"
rows_path = m.GOLDEN_DIR / "check_save_golden_rows.json"
photos_path = m.GOLDEN_DIR / "check_save_golden_photos.json"
if not photos_path.exists() or args.deliberate:
    photos = {"frozen_from": args.from_commit, "note": "The whole chain for photo counts 0, 1 and 3, and for photos staged before the outcome changed.",
              "deliberate": args.deliberate, "cases": m.compute_photo_chain(app, "inline")}
    photos_path.write_text(json.dumps(photos, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"froze {len(photos['cases'])} photo-chain cases")
need_digests = args.deliberate or not digests_path.exists()
need_rows = args.deliberate or not rows_path.exists()
if not (need_digests or need_rows):
    sys.exit("The digests and rows goldens already exist, left as they are. A golden is replaced only deliberately: pass --deliberate '<reason>'.")

result = m.compute(app, "inline", keep_rows_for=m.is_representative)
header = [
    "# Golden record for Save check: a digest of the rows written for every cell of tests/check_save_matrix.py.",
    f"# Frozen from commit {args.from_commit}, by running the frozen inline block (golden/check_save_inline_block_main.txt).",
    f"# Cells: {len(result['digests'])}.",
]
if args.deliberate:
    header.append(f"# Replaced deliberately: {args.deliberate}")
if need_digests:
    digests_path.write_text(
        "\n".join(header + [f"{key}\t{value}" for key, value in result["digests"].items()]) + "\n", encoding="utf-8"
    )
if need_rows:
    lines = [f"{json.dumps(k)}: {json.dumps(v, separators=(',', ':'))}" for k, v in result["rows"].items()]
    rows_path.write_text(
        '{"frozen_from": ' + json.dumps(args.from_commit) + ', "note": "Full rows for the representative cells; the digests file covers the whole matrix.", "cells": {\n'
        + ",\n".join(lines) + "\n}}\n", encoding="utf-8",
    )
print(f"froze {len(result['digests'])} cells ({len(result['rows'])} with full rows); digests written: {bool(need_digests)}, rows written: {bool(need_rows)}")
