#!/bin/bash
set -uo pipefail

echo "=== Running Terminus 3 Task Verifier for fleet-routing-jni-solver ==="

mkdir -p /logs/verifier
chmod 700 /logs/verifier

python3 -m pytest -v /tests/test_outputs.py -rA
rc=$?

if [ "$rc" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
  echo "=== VERIFIER PASSED: REWARD 1 ==="
else
  echo 0 > /logs/verifier/reward.txt
  echo "=== VERIFIER FAILED: REWARD 0 ==="
fi

exit 0
