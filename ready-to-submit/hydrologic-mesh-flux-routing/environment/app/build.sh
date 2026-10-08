#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Generating NetCDF meteorological datasets..."
python3 "${HERE}/generate_fixtures.py"

cd "${HERE}/rust_solver"
echo "Building Rust numerical flux solver in release mode..."
cargo build --release

echo "Build successful: ${HERE}/rust_solver/target/release/rust_solver"
