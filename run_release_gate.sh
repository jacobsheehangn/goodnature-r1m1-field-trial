#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "== Static and workbook checks =="
python tests/release_gate.py

echo
echo "== Deterministic local browser checks =="
pytest tests/test_local_app.py

echo
echo "Release gate passed."
