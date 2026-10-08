#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LD_LIBRARY_PATH="$HERE/lib:${LD_LIBRARY_PATH:-}"

java -Djava.library.path="$HERE/lib" -cp "$HERE/java_gateway/bin" com.fleet.DispatchGateway /app/data/fleet_orders.json /app/output.json
