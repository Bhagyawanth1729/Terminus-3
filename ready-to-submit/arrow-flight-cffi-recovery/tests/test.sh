#!/bin/bash
set -e

echo "=== Running Terminus 3 Task Verifier for arrow-flight-cffi-recovery ==="

python3 -m pytest -v /tests/test_outputs.py

echo "=== ALL VERIFIER TESTS PASSED ==="
