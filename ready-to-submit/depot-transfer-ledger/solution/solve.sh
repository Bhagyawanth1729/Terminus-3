#!/usr/bin/env bash
# Restore the four ledger fragment COPY books, rebuild, and run the sample batch.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="/app/x"

cp "${HERE}/fixed/a1/a.c" "${ROOT}/a1/a.c"
cp "${HERE}/fixed/b2/b.c" "${ROOT}/b2/b.c"
cp "${HERE}/fixed/c3/c.c" "${ROOT}/c3/c.c"
cp "${HERE}/fixed/d4/d.c" "${ROOT}/d4/d.c"

cd "${ROOT}"
make clean all

mkdir -p /app/output
"${ROOT}/bin/depot-ledger" \
  --parts "${ROOT}/sample/parts.dat" \
  --stock "${ROOT}/sample/opening.dat" \
  --events "${ROOT}/sample/events.dat" \
  --output /app/output

for report in closing-stock.dat open-transit.dat exceptions.dat summary.dat; do
  test -f "/app/output/${report}"
done
