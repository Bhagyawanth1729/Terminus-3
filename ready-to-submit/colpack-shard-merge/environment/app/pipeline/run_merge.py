#!/usr/bin/env python3
"""Run shard encoding and invoke the Rust merge tool."""

from __future__ import annotations

import json
import struct
import sys
import tomllib
import subprocess
import zlib
from pathlib import Path

from cpk_writer import encode_csv

HEADER_SIZE = 20


def load_config(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def body_crc32(path: Path) -> str:
    data = path.read_bytes()
    if len(data) < HEADER_SIZE + 8:
        raise ValueError("cpk too small")
    crc_target = data[:-8]
    return f"{zlib.crc32(crc_target) & 0xFFFFFFFF:08x}"


def read_schema(cpk_path: Path) -> tuple[int, list[str]]:
    data = cpk_path.read_bytes()
    if data[:4] != b"CPK2":
        raise ValueError("bad magic")
    column_count = struct.unpack_from("<I", data, 6)[0]
    row_count = struct.unpack_from("<I", data, 10)[0]
    body_length = struct.unpack_from("<I", data, 14)[0]
    body = data[HEADER_SIZE : HEADER_SIZE + body_length]
    offset = 0
    flags = data[5]
    if flags & 0x01:
        dict_count = struct.unpack_from("<I", body, offset)[0]
        offset += 4
        for _ in range(dict_count):
            entry_len = struct.unpack_from("<H", body, offset)[0]
            offset += 2 + entry_len
    names: list[str] = []
    for _ in range(column_count):
        name_len = struct.unpack_from("<H", body, offset)[0]
        offset += 2
        name = body[offset : offset + name_len].decode("utf-8")
        offset += name_len + 1 + 8
        names.append(name)
    return row_count, names


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--config":
        print("usage: run_merge.py --config <toml>", file=sys.stderr)
        return 2

    cfg = load_config(Path(sys.argv[2]))
    shards_dir = Path(cfg["shards_dir"])
    shard_names = cfg["shards"]
    cpk_dir = Path("/app/output/.shards")
    cpk_dir.mkdir(parents=True, exist_ok=True)

    cpk_paths: list[Path] = []
    for name in shard_names:
        csv_path = shards_dir / f"{name}.csv"
        cpk_path = cpk_dir / f"{name}.cpk"
        encode_csv(csv_path, cpk_path)
        cpk_paths.append(cpk_path)

    out_cpk = Path(cfg["output_cpk"])
    out_stats = Path(cfg["output_stats"])
    out_cpk.parent.mkdir(parents=True, exist_ok=True)

    merge_cmd = [cfg["colpack_bin"], "merge", "--output", str(out_cpk)]
    for cpk in cpk_paths:
        merge_cmd.extend(["--input", str(cpk)])

    subprocess.run(merge_cmd, check=True)

    total_rows = 0
    columns: list[str] | None = None
    for cpk in cpk_paths:
        rows, cols = read_schema(cpk)
        total_rows += rows
        if columns is None:
            columns = cols
        elif columns != cols:
            raise SystemExit("schema mismatch across shards")

    stats = {
        "shards": shard_names,
        "total_rows": total_rows,
        "columns": columns or [],
        "merged_crc32": body_crc32(out_cpk),
    }
    out_stats.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
