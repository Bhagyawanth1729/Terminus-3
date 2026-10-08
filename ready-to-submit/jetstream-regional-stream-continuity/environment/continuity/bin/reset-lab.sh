#!/usr/bin/env bash
set -euo pipefail
ROOT="${CONTINUITY_ROOT:-/app/continuity}"
exec "$ROOT/bin/continuityctl" reset --root "$ROOT" "$@"
