The ColPack shard merge pipeline under `/app` is broken. It encodes CSV shards into ColPack
v2 binaries, merges them with the Rust `colpack` tool, and writes a manifest — but the merged
archive and stats do not match what downstream ingestion expects.

Repair the Python encoder in `/app/pipeline/cpk_writer.py` and the Rust merger in
`/app/colpack-rs/src/main.rs` so they conform to `/app/docs/colpack_v2.md`, rebuild the merger,
and run the pipeline as:

`python3 /app/pipeline/run_merge.py --config /app/config/merge.toml`

The run must produce:

- `/app/output/merged.cpk` — a valid ColPack v2 file whose row count equals the combined
  data rows from every shard listed in the config (CSV header lines are not data rows).
- `/app/output/stats.json` — JSON with keys `shards` (array of shard base names in config
  order), `total_rows` (integer), `columns` (array of column name strings in schema order),
  and `merged_crc32` (lowercase hex CRC32 of the merged file body per the spec, excluding
  only the 8-byte footer). Indent with two spaces and end with a trailing newline.

The pipeline must also succeed on configs pointing at other shard directories with the same
schema; only paths and shard lists change.
