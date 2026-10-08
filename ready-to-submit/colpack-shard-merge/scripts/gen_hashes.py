#!/usr/bin/env python3
"""Generate golden SHA-256 hashes for verifier fixtures (author tooling only)."""

from __future__ import annotations

import csv
import hashlib
import json
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

HEADER_SIZE = 18
END_MAGIC = 0x324B5043
HAS_DICT = 0x01
VERSION = 2


@dataclass
class Column:
    name: str
    kind: str


@dataclass
class ParsedCpk:
    dictionary: list[str]
    columns: list[Column]
    payloads: list[bytes]
    row_count: int


def read_csv(path: Path) -> tuple[list[Column], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = []
        for name in reader.fieldnames or []:
            lowered = name.strip().lower()
            if lowered == "id":
                kind = "i64"
            elif lowered == "score":
                kind = "f64"
            else:
                kind = "str"
            cols.append(Column(name=name, kind=kind))
        rows = [dict(row) for row in reader]
    return cols, rows


def build_dictionary(rows: list[dict[str, str]], str_cols: list[Column]) -> list[str]:
    seen: dict[str, int] = {}
    ordered: list[str] = []
    for row in rows:
        for col in str_cols:
            value = row[col.name]
            if value not in seen:
                seen[value] = len(ordered)
                ordered.append(value)
    return ordered


def encode_dictionary(entries: list[str]) -> bytes:
    out = bytearray()
    out.extend(struct.pack("<I", len(entries)))
    for entry in entries:
        raw = entry.encode("utf-8")
        out.extend(struct.pack("<H", len(raw)))
        out.extend(raw)
    return bytes(out)


def column_payload(col: Column, rows: list[dict[str, str]], dictionary: list[str]) -> bytes:
    if col.kind == "i64":
        return b"".join(struct.pack("<q", int(row[col.name])) for row in rows)
    if col.kind == "f64":
        return b"".join(struct.pack("<d", float(row[col.name])) for row in rows)
    lookup = {value: idx for idx, value in enumerate(dictionary)}
    return b"".join(struct.pack("<I", lookup[row[col.name]]) for row in rows)


def encode_csv(csv_path: Path) -> bytes:
    columns, rows = read_csv(csv_path)
    str_cols = [c for c in columns if c.kind == "str"]
    dictionary = build_dictionary(rows, str_cols) if str_cols else []
    dict_bytes = encode_dictionary(dictionary) if dictionary else b""
    payloads = [column_payload(col, rows, dictionary) for col in columns]

    directory = bytearray()
    data_blob = bytearray()
    cursor = len(dict_bytes)
    for col, payload in zip(columns, payloads):
        col_type = {"i64": 0, "str": 1, "f64": 2}[col.kind]
        name_raw = col.name.encode("utf-8")
        directory.extend(struct.pack("<H", len(name_raw)))
        directory.extend(name_raw)
        directory.extend(struct.pack("<B", col_type))
        directory.extend(struct.pack("<II", cursor, len(payload)))
        data_blob.extend(payload)
        cursor += len(payload)

    body = dict_bytes + bytes(directory) + bytes(data_blob)
    flags = HAS_DICT if dictionary else 0
    header = struct.pack(
        "<4sBBIII",
        b"CPK2",
        VERSION,
        flags,
        len(columns),
        len(rows),
        len(body),
    )
    crc = zlib.crc32(header + body) & 0xFFFFFFFF
    footer = struct.pack("<II", crc, END_MAGIC)
    return header + body + footer


def parse_cpk(data: bytes) -> ParsedCpk:
    if data[:4] != b"CPK2":
        raise ValueError("bad magic")
    flags = data[5]
    column_count = struct.unpack_from("<I", data, 6)[0]
    row_count = struct.unpack_from("<I", data, 10)[0]
    body_length = struct.unpack_from("<I", data, 14)[0]
    body_start = HEADER_SIZE
    body = data[body_start : body_start + body_length]
    offset = 0
    dictionary: list[str] = []
    if flags & HAS_DICT:
        dict_count = struct.unpack_from("<I", body, offset)[0]
        offset += 4
        for _ in range(dict_count):
            entry_len = struct.unpack_from("<H", body, offset)[0]
            offset += 2
            dictionary.append(body[offset : offset + entry_len].decode("utf-8"))
            offset += entry_len

    columns: list[Column] = []
    payload_specs: list[tuple[int, int]] = []
    for _ in range(column_count):
        name_len = struct.unpack_from("<H", body, offset)[0]
        offset += 2
        name = body[offset : offset + name_len].decode("utf-8")
        offset += name_len
        col_type = body[offset]
        offset += 1
        data_offset = struct.unpack_from("<I", body, offset)[0]
        offset += 4
        data_length = struct.unpack_from("<I", body, offset)[0]
        offset += 4
        kind = {0: "i64", 1: "str", 2: "f64"}[col_type]
        columns.append(Column(name=name, kind=kind))
        payload_specs.append((data_offset, data_length))

    payloads: list[bytes] = []
    for data_offset, data_length in payload_specs:
        start = body_start + data_offset
        payloads.append(data[start : start + data_length])

    return ParsedCpk(dictionary, columns, payloads, row_count)


def merge_inputs(inputs: list[ParsedCpk]) -> ParsedCpk:
    schema = inputs[0].columns
    for item in inputs[1:]:
        if item.columns != schema:
            raise ValueError("schema mismatch")

    merged_dict: list[str] = []
    dict_map: dict[str, int] = {}
    for item in inputs:
        for entry in item.dictionary:
            if entry not in dict_map:
                dict_map[entry] = len(merged_dict)
                merged_dict.append(entry)

    merged_payloads = [bytearray() for _ in schema]
    merged_rows = 0
    for item in inputs:
        merged_rows += item.row_count
        for idx, col in enumerate(schema):
            chunk = item.payloads[idx]
            if col.kind in ("i64", "f64"):
                merged_payloads[idx].extend(chunk)
            else:
                rows = item.row_count
                for row_idx in range(rows):
                    start = row_idx * 4
                    old_idx = struct.unpack_from("<I", chunk, start)[0]
                    new_idx = dict_map[item.dictionary[old_idx]]
                    merged_payloads[idx].extend(struct.pack("<I", new_idx))

    return ParsedCpk(merged_dict, schema, [bytes(p) for p in merged_payloads], merged_rows)


def write_cpk(parsed: ParsedCpk) -> bytes:
    dict_bytes = encode_dictionary(parsed.dictionary) if parsed.dictionary else b""
    directory = bytearray()
    data_blob = bytearray()
    cursor = len(dict_bytes)
    for col, payload in zip(parsed.columns, parsed.payloads):
        col_type = {"i64": 0, "str": 1, "f64": 2}[col.kind]
        name_raw = col.name.encode("utf-8")
        directory.extend(struct.pack("<H", len(name_raw)))
        directory.extend(name_raw)
        directory.extend(struct.pack("<B", col_type))
        directory.extend(struct.pack("<II", cursor, len(payload)))
        data_blob.extend(payload)
        cursor += len(payload)

    body = dict_bytes + bytes(directory) + bytes(data_blob)
    flags = HAS_DICT if parsed.dictionary else 0
    header = struct.pack(
        "<4sBBIII",
        b"CPK2",
        VERSION,
        flags,
        len(parsed.columns),
        parsed.row_count,
        len(body),
    )
    crc = zlib.crc32(header + body) & 0xFFFFFFFF
    footer = struct.pack("<II", crc, END_MAGIC)
    return header + body + footer


def run_merge(shards_dir: Path, shard_names: list[str]) -> tuple[bytes, dict]:
    cpks = [parse_cpk(encode_csv(shards_dir / f"{name}.csv")) for name in shard_names]
    merged = merge_inputs(cpks)
    merged_bytes = write_cpk(merged)
    crc = f"{zlib.crc32(merged_bytes[:-8]) & 0xFFFFFFFF:08x}"
    stats = {
        "shards": shard_names,
        "total_rows": sum(c.row_count for c in cpks),
        "columns": [c.name for c in cpks[0].columns],
        "merged_crc32": crc,
    }
    return merged_bytes, stats


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    primary_dir = root / "environment" / "app" / "data"
    holdout_dir = root / "tests" / "holdout" / "data"

    merged, stats = run_merge(primary_dir, ["shard_a", "shard_b"])
    stats_bytes = (json.dumps(stats, indent=2) + "\n").encode("utf-8")

    holdout_merged, holdout_stats = run_merge(holdout_dir, ["shard_c", "shard_d"])
    holdout_stats_bytes = (json.dumps(holdout_stats, indent=2) + "\n").encode("utf-8")

    print("PRIMARY_MERGED", sha256(merged))
    print("PRIMARY_STATS", sha256(stats_bytes))
    print("HOLDOUT_MERGED", sha256(holdout_merged))
    print("HOLDOUT_STATS", sha256(holdout_stats_bytes))
    print("PRIMARY_ROWS", stats["total_rows"])
    print("HOLDOUT_ROWS", holdout_stats["total_rows"])


if __name__ == "__main__":
    main()
