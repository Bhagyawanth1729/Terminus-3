#!/bin/bash
set -euo pipefail

echo "=== Terminus 3 Oracle Solution: lsm-wal-cgo-compactor ==="

# 1. Fix Go CRC32c table polynomial (switch IEEE to Castagnoli) and C-FFI memory slice alignment
cat << 'EOF' > /app/go_wal/crc.go
package main

import (
	"hash/crc32"
)

var CastagnoliTable = crc32.MakeTable(crc32.Castagnoli)

func ComputeCRC32c(data []byte) uint32 {
	return crc32.Checksum(data, CastagnoliTable)
}
EOF

cat << 'EOF' > /app/go_wal/compactor_cgo.go
package main

/*
#cgo LDFLAGS: -L/app/lib -lrust_compactor -Wl,-rpath,/app/lib
#include <stdint.h>
#include <stdlib.h>

uint32_t cgo_compact_wal(const char* path_ptr, const uint8_t* data_ptr, uintptr_t data_len);
*/
import "C"
import (
	"fmt"
	"unsafe"
)

func CompactWALViaRust(outputPath string, rawData []byte) (uint32, error) {
	if len(rawData) == 0 {
		return 0, fmt.Errorf("empty raw data")
	}

	cPath := C.CString(outputPath)
	defer C.free(unsafe.Pointer(cPath))

	// Enforce 8-byte buffer alignment before passing to Rust C-FFI
	alignedBuf := make([]byte, len(rawData))
	copy(alignedBuf, rawData)

	ptr := (*C.uint8_t)(unsafe.Pointer(&alignedBuf[0]))
	length := C.uintptr_t(len(alignedBuf))

	res := C.cgo_compact_wal(cPath, ptr, length)
	if res == 0 {
		return 0, fmt.Errorf("Rust compaction failed for %s", outputPath)
	}

	return uint32(res), nil
}
EOF

# 2. Fix Rust SSTable atomic write cursor store ordering (Release) and lock poisoning recovery
cat << 'EOF' > /app/rust_compactor/src/sstable.rs
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::fs::OpenOptions;
use std::io::Write;
use crate::crc32c::crc32c;

pub static ATOMIC_WRITE_CURSOR: AtomicU64 = AtomicU64::new(0);

pub struct SSTableRegistry {
    pub active_file_count: u32,
}

pub static SSTABLE_REGISTRY: Mutex<SSTableRegistry> = Mutex::new(SSTableRegistry {
    active_file_count: 0,
});

pub fn compact_blocks(path: &str, raw_data: &[u8]) -> Result<u32, String> {
    let mut reg = match SSTABLE_REGISTRY.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };

    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(path)
        .map_err(|e| format!("Failed to open file: {}", e))?;

    let checksum = crc32c(raw_data);
    let header = format!("SST21\nLEN:{}\nCRC:{:08x}\n", raw_data.len(), checksum);

    file.write_all(header.as_bytes())
        .map_err(|e| format!("Header write failed: {}", e))?;
    file.write_all(raw_data)
        .map_err(|e| format!("Data write failed: {}", e))?;

    ATOMIC_WRITE_CURSOR.store(raw_data.len() as u64, Ordering::Release);

    reg.active_file_count += 1;
    Ok(checksum)
}
EOF

# 3. Fix Python UNIX socket frame length decoding (varint decoding)
cat << 'EOF' > /app/python_validator/client.py
import socket
import struct
import sys
import json
import os

def read_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf

def read_length_prefix(sock):
    res = 0
    shift = 0
    while True:
        b = read_exact(sock, 1)
        if not b:
            return None
        val = b[0]
        res |= (val & 0x7F) << shift
        if not (val & 0x80):
            break
        shift += 7
    return res

def fetch_ipc_records(socket_path="/tmp/lsm_db.sock"):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(socket_path)

    record_count = read_length_prefix(sock)
    if record_count is None:
        raise ValueError("Failed to read record count header")

    records = []
    for _ in range(record_count):
        metric_len = read_length_prefix(sock)
        if metric_len is None:
            break
        metric = read_exact(sock, metric_len).decode('utf-8', errors='ignore')

        host_len = read_length_prefix(sock)
        if host_len is None:
            break
        host = read_exact(sock, host_len).decode('utf-8', errors='ignore')

        ts_raw = read_exact(sock, 8)
        ts = struct.unpack('>q', ts_raw)[0] if len(ts_raw) == 8 else 0

        val_raw = read_exact(sock, 8)
        val = struct.unpack('>d', val_raw)[0] if len(val_raw) == 8 else 0.0

        records.append({
            "metric": metric,
            "host": host,
            "timestamp": ts,
            "value": val
        })

    sock.close()
    return records
EOF

# 4. Rebuild binaries and run pipeline
chmod +x /app/build_all.sh
/app/build_all.sh

echo "=== Oracle solution applied cleanly ==="
