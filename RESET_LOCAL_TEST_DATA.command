#!/bin/bash

set -e
cd "$(dirname "$0")"

echo "This resets only the local test data."
read -r -p "Type RESET to continue: " confirmation

if [ "$confirmation" != "RESET" ]; then
  echo "Reset cancelled."
  exit 0
fi

rm -rf "$(pwd)/local_test_data"
mkdir -p "$(pwd)/local_test_data"
echo "Local test data reset."
