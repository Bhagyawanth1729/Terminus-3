#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fixed="$here/fixed"
target=/app/claims/src/copybooks

install -m 0644 "$fixed/transaction-begin" "$target/transaction-begin"
install -m 0644 "$fixed/request-identity" "$target/request-identity"
install -m 0644 "$fixed/deductible-math" "$target/deductible-math"
install -m 0644 "$fixed/clawback-order" "$target/clawback-order"
install -m 0644 "$fixed/audit-reserve" "$target/audit-reserve"

/app/claims/bin/build-claims
