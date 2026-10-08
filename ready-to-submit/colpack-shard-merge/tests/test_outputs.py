import json
import os
import struct
import subprocess
import zlib
from pathlib import Path
import pytest

HEADER_SIZE = 20
END_MAGIC = 0x324B5043
HAS_DICT = 0x01


def test_primary_pipeline_merge():
    """Test running merge pipeline on primary data shards."""
    res = subprocess.run(
        ["python3", "/app/pipeline/run_merge.py", "--config", "/app/config/merge.toml"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"run_merge failed: {res.stderr}"

    merged_cpk = Path("/app/output/merged.cpk")
    stats_json = Path("/app/output/stats.json")

    assert merged_cpk.exists(), "merged.cpk was not created"
    assert stats_json.exists(), "stats.json was not created"

    stats = json.loads(stats_json.read_text(encoding="utf-8"))
    assert stats["shards"] == ["shard_a", "shard_b"]
    assert stats["total_rows"] == 6
    assert stats["columns"] == ["id", "name", "score"]

    data = merged_cpk.read_bytes()
    assert len(data) >= HEADER_SIZE + 8
    assert data[:4] == b"CPK2"

    flags = data[5]
    assert flags & HAS_DICT, "HAS_DICT flag should be set for string columns"

    row_count = struct.unpack_from("<I", data, 10)[0]
    assert row_count == 6

    expected_crc = struct.unpack_from("<I", data, len(data) - 8)[0]
    magic = struct.unpack_from("<I", data, len(data) - 4)[0]
    assert magic == END_MAGIC

    actual_crc = zlib.crc32(data[:-8]) & 0xFFFFFFFF
    assert actual_crc == expected_crc
    assert stats["merged_crc32"] == f"{actual_crc:08x}"


def test_holdout_pipeline_merge():
    """Test running merge pipeline on holdout data shards."""
    res = subprocess.run(
        ["python3", "/app/pipeline/run_merge.py", "--config", "/tests/holdout/config/merge.toml"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"holdout run_merge failed: {res.stderr}"

    merged_cpk = Path("/work/out/holdout_merged.cpk")
    stats_json = Path("/work/out/holdout_stats.json")

    assert merged_cpk.exists(), "holdout_merged.cpk was not created"
    assert stats_json.exists(), "holdout_stats.json was not created"

    stats = json.loads(stats_json.read_text(encoding="utf-8"))
    assert stats["shards"] == ["shard_c", "shard_d"]
    assert stats["total_rows"] == 5
    assert stats["columns"] == ["id", "name", "score"]

    data = merged_cpk.read_bytes()
    assert len(data) >= HEADER_SIZE + 8
    assert data[:4] == b"CPK2"

    row_count = struct.unpack_from("<I", data, 10)[0]
    assert row_count == 5

    expected_crc = struct.unpack_from("<I", data, len(data) - 8)[0]
    magic = struct.unpack_from("<I", data, len(data) - 4)[0]
    assert magic == END_MAGIC

    actual_crc = zlib.crc32(data[:-8]) & 0xFFFFFFFF
    assert actual_crc == expected_crc
    assert stats["merged_crc32"] == f"{actual_crc:08x}"
