#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
echo 0 > /logs/verifier/reward.txt
TEST_DIR="${TEST_DIR:-/tests}"
chmod 0755 /app/x/bin/depot-ledger /app/x/bin/* 2>/dev/null || true
chmod 0755 /app/x/build/depot-ledger-bin 2>/dev/null || true
pytest --ctrf /logs/verifier/ctrf.json "$TEST_DIR/test_outputs.py" -rA
if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
