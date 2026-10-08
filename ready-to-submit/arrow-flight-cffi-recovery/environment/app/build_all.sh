#!/bin/bash
set -e

echo "Building Rust C-FFI execution library (libarrow_exec)..."
cd /app/libarrow_exec
cargo build --release

echo "Installing Rust dynamic library..."
cp /app/libarrow_exec/target/release/libarrow_exec.so /app/flight-server/libarrow_exec.so
cp /app/libarrow_exec/target/release/libarrow_exec.so /usr/local/lib/libarrow_exec.so 2>/dev/null || cp /app/libarrow_exec/target/release/libarrow_exec.so /usr/lib/libarrow_exec.so
ldconfig 2>/dev/null || true

echo "Building Go Arrow Flight server..."
cd /app/flight-server
go build -o flight-server main.go

echo "Build complete."
