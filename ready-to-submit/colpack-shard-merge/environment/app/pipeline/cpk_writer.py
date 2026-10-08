"""Encode CSV shards into ColPack v2 binaries."""

from __future__ import annotations

import csv
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

HEADER_SIZE = 20
END_MAGIC = 0x324B5043
HAS_DICT = 0x01
VERSION = 2


@dataclass
class Column:
    name: str
    kind: str  # "i64", "str", "f64"


def _read_csv(path: Path) -> tuple[list[Column], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"empty csv: {path}")
        cols = []
        for name in reader.fieldnames:
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


def _build_dictionary(rows: list[dict[str, str]], str_cols: list[Column]) -> list[str]:
    seen: dict[str, int] = {}
    ordered: list[str] = []
    for row in rows:
        for col in str_cols:
            value = row[col.name]
            if value not in seen:
                seen[value] = len(ordered)
                ordered.append(value)
    return ordered


def _encode_dictionary(entries: list[str]) -> bytes:
    out = bytearray()
    out.extend(struct.pack("<I", len(entries)))
    for entry in entries:
        raw = entry.encode("utf-8")
        out.extend(struct.pack("<H", len(raw)))
        out.extend(raw)
    return bytes(out)


def _column_payload(col: Column, rows: list[dict[str, str]], dictionary: list[str]) -> bytes:
    if col.kind == "i64":
        return b"".join(struct.pack("<q", int(row[col.name])) for row in rows)
    if col.kind == "f64":
        return b"".join(struct.pack("<d", float(row[col.name])) for row in rows)
    lookup = {value: idx for idx, value in enumerate(dictionary)}
    return b"".join(struct.pack("<I", lookup[row[col.name]]) for row in rows)


def _flags(dictionary: list[str]) -> int:
    return HAS_DICT if dictionary else 0


def _crc32(header: bytes, body: bytes) -> int:
    return zlib.crc32(header + body) & 0xFFFFFFFF


def encode_csv(csv_path: Path, out_path: Path) -> None:
    columns, rows = _read_csv(csv_path)
    str_cols = [c for c in columns if c.kind == "str"]
    dictionary = _build_dictionary(rows, str_cols) if str_cols else []

    dict_bytes = _encode_dictionary(dictionary) if dictionary else b""
    payloads = [_column_payload(col, rows, dictionary) for col in columns]

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
    header = struct.pack(
        "<4sBBIII",
        b"CPK2",
        VERSION,
        _flags(dictionary),
        len(columns),
        len(rows),
        len(body),
    )
    crc = _crc32(header, body)
    footer = struct.pack("<II", crc, END_MAGIC)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(header + body + footer)


def encode_shards(csv_paths: Iterable[Path], cpk_dir: Path) -> list[Path]:
    cpk_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for csv_path in csv_paths:
        cpk_path = cpk_dir / (csv_path.stem + ".cpk")
        encode_csv(csv_path, cpk_path)
        outputs.append(cpk_path)
    return outputs
