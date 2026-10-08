#!/bin/bash
set -e

mkdir -p /logs/verifier

pytest -v /tests/test_outputs.py 2>&1 | tee /logs/verifier/pytest.log

if [ ${PIPESTATUS[0]} -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
    echo "VERIFIER PASSED"
else
    echo 0 > /logs/verifier/reward.txt
    echo "VERIFIER FAILED"
    exit 1
fi
