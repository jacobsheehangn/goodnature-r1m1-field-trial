#!/bin/bash

set -e
cd "$(dirname "$0")"

APP_VERSION="v8.7.6.1"
echo "R1/M1 Field Trial — ${APP_VERSION} Local launcher fix"
echo "Preparing local test environment..."

find_supported_python() {
  for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
      then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_supported_python || true)"

if [ -z "$PYTHON_BIN" ]; then
  echo
  echo "A supported Python version was not found."
  echo "This app requires Python 3.10 or newer."
  echo
  if command -v brew >/dev/null 2>&1; then
    echo "Install Python 3.12 with:"
    echo "  brew install python@3.12"
  else
    echo "Install Python 3.12 from python.org, then run this file again."
  fi
  echo
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi

PYTHON_VERSION="$($PYTHON_BIN -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
echo "Using Python ${PYTHON_VERSION}: ${PYTHON_BIN}"

# Remove a virtual environment created with an unsupported or different Python.
if [ -d ".venv" ]; then
  VENV_OK="false"
  if [ -x ".venv/bin/python" ]; then
    if .venv/bin/python - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
    then
      VENV_BASE="$(.venv/bin/python -c 'import sys; print(sys.base_prefix)')"
      SELECTED_BASE="$($PYTHON_BIN -c 'import sys; print(sys.prefix)')"
      if [ "$VENV_BASE" = "$SELECTED_BASE" ]; then
        VENV_OK="true"
      fi
    fi
  fi

  if [ "$VENV_OK" != "true" ]; then
    echo "Rebuilding the local environment with Python ${PYTHON_VERSION}..."
    rm -rf .venv
  fi
fi

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
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
