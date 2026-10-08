# ColPack v2 wire format

ColPack v2 is a columnar binary container used between the Python shard encoder and the
Rust merge tool. All multi-byte integers are little-endian. CRC32 uses the IEEE polynomial
(initial value `0xFFFFFFFF`, final XOR `0xFFFFFFFF`).

## File layout

| Region | Size | Contents |
|--------|------|----------|
| Header | 20 bytes | See below |
| Body | `body_length` bytes | Dictionary (optional), column directory, column payloads |
| Footer | 8 bytes | `crc32` u32, `end_magic` u32 (`0x324B5043`) |

The CRC covers every byte from file start through the last body byte (header + body). It
does not include the footer.

### Header

| Offset | Type | Field |
|--------|------|-------|
| 0 | [u8; 4] | Magic `CPK2` |
| 4 | u8 | Version, must be `2` |
| 5 | u8 | Flags — bit 0 (`HAS_DICT`) set when a string dictionary block is present |
| 6 | u32 | Column count |
| 10 | u32 | Row count (data rows only) |
| 14 | u32 | Body length in bytes |

### Body

When `HAS_DICT` is set, the body begins with a dictionary block:

- `dict_count` u32
- For each entry: `entry_len` u16 followed by UTF-8 bytes

The column directory follows immediately after the dictionary (or at body start when no
dictionary). There is one directory entry per column:

| Field | Type |
|-------|------|
| `name_len` | u16 |
| `name` | UTF-8 bytes |
| `col_type` | u8 — `0` = i64, `1` = string (dictionary index), `2` = f64 |
| `data_offset` | u32 — byte offset relative to **body start** |
| `data_length` | u32 |

Column payloads sit at `body_start + data_offset` within the file (body start is the byte
immediately following the 20-byte header).

Payload encoding per row:

- i64: 8-byte signed integer
- string: u32 dictionary index
- f64: IEEE754 binary64

### Merge semantics

The merge tool accepts multiple v2 files sharing identical column names and types (in order).
The output file's row count is the **sum** of input row counts. Dictionary entries are unioned
in first-seen order; string indices are remapped accordingly.
