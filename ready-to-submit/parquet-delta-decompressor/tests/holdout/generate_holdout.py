import os
import pyarrow as pa
import pyarrow.parquet as pq
import struct


def encode_varint(n: int) -> bytes:
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


def create_holdout_dataset(output_parquet_path: str):
    initial_ts = 1800000000000

    delta_stream = bytearray()
    delta_stream.extend(struct.pack("<q", initial_ts))

    # Holdout pattern with varied delta bit widths and 45 negative deltas
    pattern = [8000, -4000, 3000, -1000, 6000, -2500, 1500, 4500, -3500, 2000]
    num_cycles = 150

    actual_neg_count = 0
    for _ in range(num_cycles):
        for val in pattern:
            if val < 0:
                actual_neg_count += 1
            delta_stream.append(16)
            delta_stream.extend(struct.pack("<h", val))

    # Dictionary with 250 entries (2-byte varint LEB128 header: 0xFA, 0x01)
    status_options = ["STATUS_OK", "WARN_LATENCY", "ERR_TIMEOUT", "CRIT_DISK_FULL"]
    dict_stream = bytearray()
    dict_stream.extend(encode_varint(250))

    for i in range(250):
        tag = status_options[i % len(status_options)]
        tag_bytes = tag.encode("utf-8")
        dict_stream.append(len(tag_bytes))
        dict_stream.extend(tag_bytes)

    metadata = {
        b"delta_payload": bytes(delta_stream),
        b"dict_payload": bytes(dict_stream),
    }

    schema = pa.schema([("dummy_col", pa.int32())], metadata=metadata)
    table = pa.Table.from_arrays([pa.array([1])], schema=schema)

    os.makedirs(os.path.dirname(os.path.abspath(output_parquet_path)), exist_ok=True)
    pq.write_table(table, output_parquet_path)
    print(f"Generated holdout dataset at {output_parquet_path} (neg_count={actual_neg_count})")


if __name__ == "__main__":
    holdout_file = os.path.join(os.path.dirname(__file__), "edge_telemetry.parquet")
    create_holdout_dataset(holdout_file)
