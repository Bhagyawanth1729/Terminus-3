#!/bin/bash
set -euo pipefail

mkdir -p /app/lib /app/bin /app/sst

echo "=== Building Rust Compactor dynamic library ==="
cd /app/rust_compactor
cargo build --release
cp /app/rust_compactor/target/release/librust_compactor.so /app/lib/librust_compactor.so

echo "=== Building Go WAL Compactor service ==="
cd /app/go_wal
go build -o /app/bin/go_wal_service .

echo "=== Running Go WAL service & Python IPC Validator ==="
rm -f /tmp/lsm_db.sock
/app/bin/go_wal_service &
GO_PID=$!

sleep 2

python3 /app/python_validator/run_pipeline.py /app/sst /tmp/lsm_db.sock /app/output.json

wait $GO_PID || true
echo "=== Build & Pipeline completed successfully ==="
