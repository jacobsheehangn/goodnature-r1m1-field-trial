"""Freezes what a Camera review save writes, from the frozen inline block (never from the extracted function). Run once, against main:
    R1M1_ENVIRONMENT=local R1M1_ALLOW_NO_AUTH=true R1M1_SEED_MODE=clean R1M1_DATA_DIR=$(mktemp -d) PYTHONPATH=.:tests python tests/golden/freeze_camera_review.py --from-commit <sha>
Refuses to overwrite an existing golden. The golden is never edited to make a test pass."""
import argparse, json, sys
import app
import camera_review_matrix as m

parser = argparse.ArgumentParser(); parser.add_argument("--from-commit", required=True); args = parser.parse_args()
path = m.GOLDEN_DIR / "camera_review_golden.json"
if path.exists():
    sys.exit(f"{path.name} already exists and is not replaced.")
r = m.compute(app, "inline", keep_rows=lambda c: True)
lines = [f"{json.dumps(k)}: {json.dumps({'digest': r['digests'][k], 'rows': v}, separators=(',', ':'))}" for k, v in r["rows"].items()]
path.write_text('{"frozen_from": ' + json.dumps(args.from_commit) + ', "cells": {\n' + ",\n".join(lines) + "\n}}\n", encoding="utf-8")
print(f"froze {len(lines)} cells")
