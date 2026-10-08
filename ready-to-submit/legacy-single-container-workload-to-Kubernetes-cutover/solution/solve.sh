#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
rm -rf /app/k8s
mkdir -p /app/k8s
cp -a "$ROOT/k8s/." /app/k8s/
