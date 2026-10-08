import argparse
import json
import os
import sys
import pyarrow.parquet as pq
from collections import Counter
from delta_decoder import decode_timestamps, decode_dictionary


def process_telemetry(data_path: str, out_path: str):
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Input file not found: {data_path}")

    # Read Parquet file metadata & custom binary payload columns
    table = pq.read_table(data_path)
    meta = table.schema.metadata or {}

    # Extracts binary blobs stored in parquet key_value_metadata or custom columns
    delta_bytes = meta.get(b"delta_payload", None)
    dict_bytes = meta.get(b"dict_payload", None)

    if delta_bytes is None or dict_bytes is None:
        # Fallback to column buffer payload if not in metadata
        if "delta_payload" in table.column_names:
            delta_bytes = table.column("delta_payload")[0].as_py()
        if "dict_payload" in table.column_names:
            dict_bytes = table.column("dict_payload")[0].as_py()

    if not delta_bytes or not dict_bytes:
        raise ValueError("Parquet file missing required delta_payload or dict_payload binary data")

    # Decode timestamps and negative delta count using native Rust library
    timestamps, neg_count = decode_timestamps(delta_bytes)

    # Decode dictionary status tags using native Rust library
    status_tags = decode_dictionary(dict_bytes)

    if not timestamps:
        report = {
            "total_records": 0,
            "min_timestamp": 0,
            "max_timestamp": 0,
            "negative_delta_count": 0,
            "mean_delta_ms": 0.0,
            "status_counts": {},
        }
    else:
        total_records = len(timestamps)
        min_ts = min(timestamps)
        max_ts = max(timestamps)

        # Calculate mean inter-arrival delta
        if total_records > 1:
            deltas = [timestamps[i] - timestamps[i - 1] for i in range(1, total_records)]
            mean_delta = float(sum(deltas)) / len(deltas)
        else:
            mean_delta = 0.0

        # Frequency count of status tags
        counts_map = dict(Counter(status_tags))
        sorted_status_counts = {k: counts_map[k] for k in sorted(counts_map.keys())}

        report = {
            "total_records": total_records,
            "min_timestamp": min_ts,
            "max_timestamp": max_ts,
            "negative_delta_count": neg_count,
            "mean_delta_ms": round(mean_delta, 2),
            "status_counts": sorted_status_counts,
        }

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    print(f"Successfully generated summary report at {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Telemetry Parquet Delta Query Pipeline")
    parser.add_argument("--data", required=True, help="Path to input parquet data file")
    parser.add_argument("--out", required=True, help="Path to output JSON report file")

    args = parser.parse_args()
    process_telemetry(args.data, args.out)


if __name__ == "__main__":
    main()
