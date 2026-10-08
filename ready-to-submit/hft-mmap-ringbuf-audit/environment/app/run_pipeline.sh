#!/bin/bash
set -e

export LD_LIBRARY_PATH=/app/lib:$LD_LIBRARY_PATH

TICK_FILE=${1:-"/app/data/ticks_sample.bin"}
OUTPUT_FILE=${2:-"/app/output.json"}
EXPECTED_TRADES=${3:-1000}
SHM_PATH="/tmp/orderbook_ring.buf"

rm -f "$SHM_PATH" /tmp/intermediate_batch.json "$OUTPUT_FILE"

# Start Go compliance listener in background
/app/go_compliance_bin "$SHM_PATH" "$EXPECTED_TRADES" &
GO_PID=$!

sleep 0.2

# Publish tick dataset via Rust producer
/app/rust_producer "$TICK_FILE" "$SHM_PATH"

# Wait for Go compliance processor
wait $GO_PID

# Execute Java audit ledger service
java -jar /app/java_audit.jar /tmp/intermediate_batch.json "$OUTPUT_FILE"

echo "Pipeline execution completed. Output generated at $OUTPUT_FILE"
