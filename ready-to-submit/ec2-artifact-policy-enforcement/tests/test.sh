#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
echo 0 > /logs/verifier/reward.txt
TEST_DIR="${TEST_DIR:-/tests}"
ROOT="${ENFORCER_ROOT:-/app/enforcer}"
cd "$ROOT" || true
if [ -d "$ROOT" ] && command -v go >/dev/null 2>&1; then
  if go build -o /tmp/artifactguard ./cmd/artifactguard; then
    export AG_BIN=/tmp/artifactguard
  fi
fi
python3 -m pytest --ctrf /logs/verifier/ctrf.json "$TEST_DIR/test_outputs.py" -rA
if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
