#!/bin/bash
# Oracle solution.
#
# cpk_writer.py had two spec violations:
#   1. HAS_DICT was never set, so the Rust parser skipped the dictionary block and misaligned
#      every column directory entry for string-encoded shards.
#   2. CRC32 was computed over the body alone; the spec covers header + body.
#
# colpack-rs/src/main.rs had two merge/parser bugs:
#   1. Column payloads were read at the raw directory offset instead of body_start + offset.
#   2. merge_inputs kept the max shard row count instead of summing row counts.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cp "$HERE/cpk_writer.py" /app/pipeline/cpk_writer.py
cp "$HERE/main.rs" /app/colpack-rs/src/main.rs

cd /app/colpack-rs
cargo build --release

python3 /app/pipeline/run_merge.py --config /app/config/merge.toml

sha256sum /app/output/merged.cpk /app/output/stats.json
