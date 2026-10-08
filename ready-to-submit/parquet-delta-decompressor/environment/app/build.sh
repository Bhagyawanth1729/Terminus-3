#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HERE/lib"

echo "Building native_delta Rust library..."
cargo build --release --manifest-path "$HERE/native_delta/Cargo.toml"

cp "$HERE/native_delta/target/release/libdeltaparquet.so" "$HERE/lib/libdeltaparquet.so"
echo "Successfully built and deployed $HERE/lib/libdeltaparquet.so"
