#!/bin/bash
# Restore Ansible and the Go module to the contract, then apply twice.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXED="$HERE/fixed"

test -f /app/environment/docs/requirements.md

# Replace trees wholesale so drifted files that only exist on the broken side
# (for example a leftover stats.go) cannot survive beside the fixed sources.
rm -rf /app/environment/ansible /app/environment/ci-server
cp -a "$FIXED/ansible" /app/environment/ansible
cp -a "$FIXED/ci-server" /app/environment/ci-server

/app/bin/ci-server-apply
/app/bin/ci-server-apply

test -s /app/var/ci-server/state/deploy-report.json
