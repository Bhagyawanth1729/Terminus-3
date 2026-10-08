#!/usr/bin/env bash
set -euo pipefail
ROOT="${ENFORCER_ROOT:-/app/enforcer}"
SOLUTION_ROOT="${SOLUTION_ROOT:-/solution}"
BIN_OUT="${ARTIFACTGUARD_BIN:-/usr/local/bin/artifactguard}"
install -m 0644 "$SOLUTION_ROOT/files/platform/policy.go" "$ROOT/internal/platform/policy.go"
install -m 0644 "$SOLUTION_ROOT/files/platform/cache.go" "$ROOT/internal/platform/cache.go"
install -m 0644 "$SOLUTION_ROOT/files/platform/exceptions.go" "$ROOT/internal/platform/exceptions.go"
install -m 0644 "$SOLUTION_ROOT/files/platform/permit.go" "$ROOT/internal/platform/permit.go"
install -m 0644 "$SOLUTION_ROOT/files/platform/state.go" "$ROOT/internal/platform/state.go"
install -m 0644 "$SOLUTION_ROOT/files/platform/audit.go" "$ROOT/internal/platform/audit.go"
install -m 0644 "$SOLUTION_ROOT/files/platform/replay.go" "$ROOT/internal/platform/replay.go"
install -m 0644 "$SOLUTION_ROOT/files/platform/evidence_runtime.go" "$ROOT/internal/platform/evidence_runtime.go"
install -m 0644 "$SOLUTION_ROOT/files/platform/journal_runtime.go" "$ROOT/internal/platform/journal_runtime.go"
install -m 0644 "$SOLUTION_ROOT/files/platform/engine.go" "$ROOT/internal/platform/engine.go"
install -m 0644 "$SOLUTION_ROOT/files/core/engine.go" "$ROOT/internal/core/engine.go"
install -m 0644 "$SOLUTION_ROOT/files/cmd/main.go" "$ROOT/cmd/artifactguard/main.go"
cd "$ROOT"
gofmt -w cmd/artifactguard/main.go internal/core/engine.go internal/platform/policy.go internal/platform/cache.go internal/platform/exceptions.go internal/platform/permit.go internal/platform/state.go internal/platform/audit.go internal/platform/replay.go internal/platform/evidence_runtime.go internal/platform/journal_runtime.go internal/platform/engine.go
go test ./...
go build -o "$BIN_OUT" ./cmd/artifactguard
