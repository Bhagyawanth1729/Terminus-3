import os
import pyarrow as pa
import pyarrow.parquet as pq
import struct


def encode_varint(n: int) -> bytes:
    """Encodes an integer into LEB128 varint format."""
    buf = bytearray()
    while True:
        towrite = n & 0x7F
        n >>= 7
        if n:
            buf.append(towrite | 0x80)
        else:
            buf.append(towrite)
            break
    return bytes(buf)


def create_telemetry_dataset(output_parquet_path: str, is_edge_holdout: bool = False):
    initial_ts = 1700000000000

    # Build binary delta stream payload
    delta_stream = bytearray()
    delta_stream.extend(struct.pack("<q", initial_ts))

    # Generate sequence of deltas including negative deltas (out-of-order timestamps)
    pattern = [5000, 3000, -2000, 4000, -1500, 6000, 2500, -1000, 3500, 4500]
    num_cycles = 100 if not is_edge_holdout else 150

    actual_neg_count = 0
    for _ in range(num_cycles):
        for val in pattern:
            if val < 0:
                actual_neg_count += 1
            # Pack as 16-bit signed delta
            delta_stream.append(16)  # 16 bits per delta
            packed_val = struct.pack("<h", val)
            delta_stream.extend(packed_val)

    # Build binary dictionary payload with LEB128 varint header (150 entries >= 128)
    status_options = ["STATUS_OK", "WARN_LATENCY", "ERR_TIMEOUT"]
    dict_stream = bytearray()

    total_dict_entries = 150 if not is_edge_holdout else 200
    dict_stream.extend(encode_varint(total_dict_entries))

    for i in range(total_dict_entries):
        tag = status_options[i % len(status_options)]
        tag_bytes = tag.encode("utf-8")
        dict_stream.append(len(tag_bytes))
        dict_stream.extend(tag_bytes)

    # Write into Parquet schema & metadata
    metadata = {
        b"delta_payload": bytes(delta_stream),
        b"dict_payload": bytes(dict_stream),
    }

    # Dummy table with metadata
    schema = pa.schema(
        [("dummy_col", pa.int32())],
        metadata=metadata,
    )
    table = pa.Table.from_arrays([pa.array([1])], schema=schema)

    os.makedirs(os.path.dirname(os.path.abspath(output_parquet_path)), exist_ok=True)
    pq.write_table(table, output_parquet_path)
    print(f"Generated {output_parquet_path} (actual_neg_count={actual_neg_count})")


if __name__ == "__main__":
    create_telemetry_dataset("/app/data/telemetry.parquet", is_edge_holdout=False)
