#!/bin/bash

set -e
cd "$(dirname "$0")"

echo "R1/M1 Field Trial — v8.6.73 Field Pilot Mode"
echo "Preparing local test environment..."

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 could not be found."
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

export R1M1_ENVIRONMENT="local"
export R1M1_ALLOW_NO_AUTH="true"
export R1M1_SEED_MODE="demo"
export R1M1_DATA_DIR="$(pwd)/local_test_data"

mkdir -p "$R1M1_DATA_DIR"

echo
echo "Opening http://localhost:8501"
echo "Keep this window open while testing."
echo "Press Control-C when finished."
echo

exec python -m streamlit run app.py \
  --server.address localhost \
  --server.port 8501 \
  --server.headless false \
  --browser.gatherUsageStats false
