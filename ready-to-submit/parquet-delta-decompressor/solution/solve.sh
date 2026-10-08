#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/app"

echo "Applying fix to native_delta/src/decoder.rs..."
cat << 'EOF' > "$APP_DIR/native_delta/src/decoder.rs"
pub struct DeltaDecoder;

impl DeltaDecoder {
    /// Decodes a stream of packed delta values starting from initial_ts.
    /// Returns count of decoded timestamps written into out_buf, and count of negative deltas encountered.
    pub fn decode_stream(
        compressed: &[u8],
        out_buf: &mut [i64],
    ) -> Result<(usize, usize), &'static str> {
        if compressed.len() < 8 {
            return Err("Compressed buffer too short for header");
        }

        // Header: Initial timestamp (8 bytes, little endian)
        let initial_ts = i64::from_le_bytes(compressed[0..8].try_into().unwrap());
        if out_buf.is_empty() {
            return Ok((0, 0));
        }

        out_buf[0] = initial_ts;
        let mut curr_ts = initial_ts;
        let mut out_idx = 1;
        let mut neg_count = 0;

        let mut byte_idx = 8;
        while byte_idx < compressed.len() && out_idx < out_buf.len() {
            let bits_per_delta = compressed[byte_idx] as usize;
            byte_idx += 1;

            if bits_per_delta == 0 {
                continue;
            }

            let num_bytes_per_delta = (bits_per_delta + 7) / 8;
            if byte_idx + num_bytes_per_delta > compressed.len() {
                break;
            }

            let mut raw_bits: u64 = 0;
            for i in 0..num_bytes_per_delta {
                raw_bits |= (compressed[byte_idx + i] as u64) << (i * 8);
            }
            byte_idx += num_bytes_per_delta;

            // FIXED: Sign-extend signed deltas properly according to bit width
            let signed_delta: i64 = match bits_per_delta {
                8 => (raw_bits as u8 as i8) as i64,
                16 => (raw_bits as u16 as i16) as i64,
                32 => (raw_bits as u32 as i32) as i64,
                64 => raw_bits as i64,
                _ => raw_bits as i64,
            };

            if signed_delta < 0 {
                neg_count += 1;
            }

            curr_ts = curr_ts.wrapping_add(signed_delta);
            out_buf[out_idx] = curr_ts;
            out_idx += 1;
        }

        Ok((out_idx, neg_count))
    }
}
EOF

echo "Applying fix to native_delta/src/dictionary.rs..."
cat << 'EOF' > "$APP_DIR/native_delta/src/dictionary.rs"
pub struct DictionaryDecoder;

fn read_varint(bytes: &[u8]) -> Result<(usize, usize), &'static str> {
    let mut res: u64 = 0;
    let mut shift = 0;
    for (i, &b) in bytes.iter().enumerate() {
        res |= ((b & 0x7f) as u64) << shift;
        shift += 7;
        if (b & 0x80) == 0 {
            return Ok((res as usize, i + 1));
        }
    }
    Err("Invalid varint")
}

impl DictionaryDecoder {
    /// Decodes a dictionary page binary buffer into indexed string strings.
    pub fn decode_dictionary(dict_bytes: &[u8]) -> Result<Vec<String>, &'static str> {
        if dict_bytes.is_empty() {
            return Err("Dictionary bytes empty");
        }

        // FIXED: Parse LEB128 varint header for entry count and byte offset
        let (entry_count, mut offset) = read_varint(dict_bytes)?;

        let mut strings = Vec::with_capacity(entry_count);
        for _ in 0..entry_count {
            if offset >= dict_bytes.len() {
                break;
            }
            let str_len = dict_bytes[offset] as usize;
            offset += 1;
            if offset + str_len > dict_bytes.len() {
                break;
            }
            let s = String::from_utf8_lossy(&dict_bytes[offset..offset + str_len]).to_string();
            offset += str_len;
            strings.push(s);
        }

        Ok(strings)
    }
}
EOF

echo "Applying fix to src/delta_decoder.py..."
cat << 'EOF' > "$APP_DIR/src/delta_decoder.py"
import ctypes
import os
import sys

_lib_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib", "libdeltaparquet.so")

try:
    _lib = ctypes.CDLL(_lib_path)
except Exception as e:
    _lib = None


def is_library_available():
    return _lib is not None


if _lib:
    # FIXED: Use c_uint64 for buffer length parameter declarations
    _lib.decode_delta_stream.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_int64),
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint64),
    ]
    _lib.decode_delta_stream.restype = ctypes.c_int32

    _lib.decode_dictionary_stream.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_uint64,
        ctypes.c_char_p,
        ctypes.c_uint64,
    ]
    _lib.decode_dictionary_stream.restype = ctypes.c_int32


def decode_timestamps(compressed_bytes: bytes, max_records: int = 100000):
    if not _lib:
        raise RuntimeError(f"Native library not loaded from {_lib_path}")

    c_compressed = (ctypes.c_uint8 * len(compressed_bytes)).from_buffer_copy(compressed_bytes)
    out_buf = (ctypes.c_int64 * max_records)()
    neg_count = ctypes.c_uint64(0)

    res = _lib.decode_delta_stream(
        c_compressed,
        len(compressed_bytes),
        out_buf,
        max_records,
        ctypes.byref(neg_count),
    )

    if res < 0:
        raise ValueError(f"Delta decoding failed with status code {res}")

    timestamps = [out_buf[i] for i in range(res)]
    return timestamps, neg_count.value


def decode_dictionary(dict_bytes: bytes):
    if not _lib:
        raise RuntimeError(f"Native library not loaded from {_lib_path}")

    c_dict = (ctypes.c_uint8 * len(dict_bytes)).from_buffer_copy(dict_bytes)
    max_json = 65536
    json_buf = ctypes.create_string_buffer(max_json)

    res = _lib.decode_dictionary_stream(
        c_dict,
        len(dict_bytes),
        json_buf,
        max_json,
    )

    if res < 0:
        raise ValueError(f"Dictionary decoding failed with status code {res}")

    joined_str = json_buf.value.decode("utf-8")
    return joined_str.split(",") if joined_str else []
EOF

echo "Rebuilding native library..."
chmod +x "$APP_DIR/build.sh"
"$APP_DIR/build.sh"

echo "Running query pipeline to generate output..."
python3 "$APP_DIR/src/query_pipeline.py" --data "$APP_DIR/data/telemetry.parquet" --out "$APP_DIR/out/report.json"

echo "Oracle solution completed successfully."
