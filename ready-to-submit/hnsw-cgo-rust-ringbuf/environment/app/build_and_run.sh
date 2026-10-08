#!/bin/bash
set -euo pipefail

APP_DIR="/app"
RINGBUF_PATH="/tmp/hnsw_ring.buf"
OUTPUT_PATH="/app/output.json"

echo "=== Building Rust C-FFI Shared Library (librust_hnsw) ==="
cd "$APP_DIR/librust_hnsw"
cargo build --release

echo "=== Building Go Retrieval Server ==="
cd "$APP_DIR/go-retrieval-server"
go build -o go_retrieval_server .

echo "=== Ensuring Dataset Exists ==="
if [ ! -f "$APP_DIR/dataset/embeddings.bin" ]; then
    python3 "$APP_DIR/generate_data.py"
fi

rm -f "$RINGBUF_PATH"

echo "=== Executing Go Retrieval Server ==="
./go_retrieval_server \
    -embeddings "$APP_DIR/dataset/embeddings.bin" \
    -queries "$APP_DIR/dataset/queries.bin" \
    -ringbuf "$RINGBUF_PATH" \
    -k 10

echo "=== Executing Python Reranker ==="
python3 "$APP_DIR/python-reranker/reranker.py" "$RINGBUF_PATH" "$OUTPUT_PATH"

echo "=== Retrieval Pipeline Run Complete ==="
