The telemetry processing script at `/app/src/query_pipeline.py` is failing to correctly decode timestamp streams and dictionary tags from custom Parquet files. When executed against `/app/data/telemetry.parquet`, the underlying native dynamic library (`/app/lib/libdeltaparquet.so`) produces corrupted timestamp metrics on out-of-order events and incorrect status tag frequencies.

Fix the issues in `/app/native_delta` and `/app/src` so that running `python3 /app/src/query_pipeline.py --data /app/data/telemetry.parquet --out /app/out/report.json` produces the correct summary report.

The output at `/app/out/report.json` must be a JSON file indented by 2 spaces ending with a newline. It must contain the following top-level keys:
- `"total_records"`: (integer) Total number of telemetry records decoded.
- `"min_timestamp"`: (integer) Minimum decoded timestamp in milliseconds.
- `"max_timestamp"`: (integer) Maximum decoded timestamp in milliseconds.
- `"negative_delta_count"`: (integer) Count of events where delta-of-delta timestamp difference was negative.
- `"mean_delta_ms"`: (float rounded to 2 decimal places) Mean inter-arrival delta in milliseconds.
- `"status_counts"`: (object) Frequency map of status tags decoded from the dictionary page (keys sorted alphabetically).

If source files in `/app/native_delta` are modified, rebuild the shared library using `/app/build.sh`. The query script must remain driveable as `python3 /app/src/query_pipeline.py --data <file> --out <file>`.
