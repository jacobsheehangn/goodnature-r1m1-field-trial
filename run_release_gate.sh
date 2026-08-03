#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "== Static and workbook checks =="
python tests/release_gate.py

echo
echo "== Live browser checks =="
if [[ -z "${R1M1_TEST_URL:-}" || -z "${R1M1_TEST_PASSWORD:-}" ]]; then
  echo "Live tests skipped: set R1M1_TEST_URL and R1M1_TEST_PASSWORD."
  exit 0
fi

pytest tests/test_live_app.py
