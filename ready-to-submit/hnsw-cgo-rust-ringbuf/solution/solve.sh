#!/bin/bash
set -euo pipefail

APP_DIR="/app"

echo "=== Applying Fix 1: Go cgo uint64 Node ID Cast (hnsw_bridge.go) ==="
# Replace `signedID := int64(cRes.node_id)` and negative check with direct uint64 preservation
sed -i 's/signedID := int64(cRes\.node_id)/nodeID := uint64(cRes.node_id)/g' "$APP_DIR/go-retrieval-server/hnsw_bridge.go"
sed -i 's/if signedID < 0 {/if false {/g' "$APP_DIR/go-retrieval-server/hnsw_bridge.go"
sed -i 's/nodeID := uint64(signedID)/_ = nodeID/g' "$APP_DIR/go-retrieval-server/hnsw_bridge.go"

echo "=== Applying Fix 2: Rust Atomic Write Head Release Fence (ringbuf.rs) ==="
# Replace `Ordering::Relaxed` with `Ordering::Release` in write_head atomic store
sed -i 's/write_head_atomic\.store(next_head, Ordering::Relaxed);/write_head_atomic.store(next_head, Ordering::Release);/g' "$APP_DIR/librust_hnsw/src/ringbuf.rs"

echo "=== Applying Fix 3: Go Context Cancellation Handle Free (stream_handler.go) ==="
# Defer C.hnsw_free_search_ctx(searchCtx) immediately after handle creation
sed -i '/searchCtx := C\.hnsw_create_search_ctx(h\.bridge\.indexC)/a \tdefer C.hnsw_free_search_ctx(searchCtx)' "$APP_DIR/go-retrieval-server/stream_handler.go"

echo "=== Rebuilding Component Shared Libraries and Binaries ==="
cd "$APP_DIR/librust_hnsw"
cargo build --release

cd "$APP_DIR/go-retrieval-server"
go build -o go_retrieval_server .

echo "=== Running Full Benchmark Retrieval Pipeline ==="
/app/build_and_run.sh

echo "=== Oracle Fix Applied & Executed Successfully ==="
