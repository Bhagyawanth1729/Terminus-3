#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "=== Building Rust C-FFI / JNI solver library ==="
cd "$HERE/solver_rust"
cargo build --release

mkdir -p "$HERE/lib"
cp "$HERE/solver_rust/target/release/libsolver_rust.so" "$HERE/lib/"

echo "=== Building Java Dispatch Gateway ==="
cd "$HERE/java_gateway"
mkdir -p bin
javac -d bin src/main/java/com/fleet/DispatchGateway.java

echo "=== Build Complete ==="
