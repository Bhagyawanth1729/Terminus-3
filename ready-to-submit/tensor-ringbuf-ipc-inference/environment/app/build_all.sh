#!/bin/bash
set -e

echo "=== Building Rust Tensor Engine ==="
cd /app/rust-engine
cargo build --release

echo "=== Installing libtensor_engine.so ==="
cp /app/rust-engine/target/release/libtensor_engine.so /usr/local/lib/
cp /app/rust-engine/target/release/libtensor_engine.so /app/go-ingress/
ldconfig || true

echo "=== Building Go Ingress Server ==="
cd /app/go-ingress
go build -o ingress-server .

echo "=== Build Complete ==="
