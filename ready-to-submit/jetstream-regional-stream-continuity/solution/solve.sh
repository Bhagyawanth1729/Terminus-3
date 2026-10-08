#!/usr/bin/env bash
set -euo pipefail
ROOT="${CONTINUITY_ROOT:-/app/continuity}"
FIXED="/solution/fixed"
install -m 0644 "$FIXED/publish.py" "$ROOT/continuity/publish.py"
install -m 0644 "$FIXED/generation.py" "$ROOT/continuity/generation.py"
install -m 0644 "$FIXED/consumers.py" "$ROOT/continuity/consumers.py"
install -m 0644 "$FIXED/reconcile.py" "$ROOT/continuity/reconcile.py"
install -m 0644 "$FIXED/replay.py" "$ROOT/continuity/replay.py"
install -m 0644 "$FIXED/fencing.py" "$ROOT/continuity/fencing.py"
install -m 0644 "$FIXED/retention.py" "$ROOT/continuity/retention.py"
install -m 0644 "$FIXED/runtime.py" "$ROOT/continuity/runtime.py"
install -m 0644 "$FIXED/continuity.json" "$ROOT/config/continuity.json"
PYTHON="$(command -v python3)"
if [[ -x /opt/continuity-venv/bin/python ]]; then
  PYTHON="/opt/continuity-venv/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi
"$PYTHON" -m py_compile \
    "$ROOT/continuity/model.py" \
    "$ROOT/continuity/store.py" \
    "$ROOT/continuity/policy.py" \
    "$ROOT/continuity/engine.py" \
    "$ROOT/continuity/publish.py" \
    "$ROOT/continuity/generation.py" \
    "$ROOT/continuity/consumers.py" \
    "$ROOT/continuity/reconcile.py" \
    "$ROOT/continuity/replay.py" \
    "$ROOT/continuity/fencing.py" \
    "$ROOT/continuity/retention.py" \
    "$ROOT/continuity/runtime.py" \
    "$ROOT/continuity/cli.py"

# Preserve inherited incident rows. verify exits 2 while gaps remain;
# report materialization must still succeed.
set +e
"$ROOT/bin/continuityctl" verify --compact >/tmp/continuity-final-verify.json
verify_status=$?
set -e
if [[ "$verify_status" -ne 0 && "$verify_status" -ne 2 ]]; then
  exit "$verify_status"
fi
test -s "$ROOT/out/health.json"
test -s "$ROOT/out/reconciliation.json"
