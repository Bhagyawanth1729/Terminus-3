# LSM Database Engine Wire Specification (v2.1)

## 1. Checksum Specification
- **Algorithm**: Castagnoli CRC32c (Polynomial `0x82F63B78` / Reflected `0x1EDC6F41`).
- **Scope**: Calculated across all WAL entry payloads and SSTable block headers.
- **Note**: Do NOT use IEEE 802.3 CRC32 (`0xEDB88320`), as Castagnoli is hardware-accelerated on modern CPUs (`CRC32C`).

## 2. Go <-> Rust C-FFI Data Alignment
- **Memory Alignment**: C-FFI entry pointers passed into `cgo_compact_wal` must be 8-byte aligned (`uint64` / `*const u64` boundary). Passing unaligned pointer offsets derived from dynamic byte slices will cause misaligned memory reads and SIMD compaction traps.
- **Atomic Operations**: All dirty page write cursor stores (`ATOMIC_WRITE_CURSOR`) must use `Ordering::Release` (or `Ordering::SeqCst`) before returning block handles to Go, ensuring memory writes are flushed before reader consumption.
- **Mutex Poisoning**: The SSTable registry mutex must safely handle or recover from lock poisoning (`poisoned.into_inner()`) if a previous compaction iteration panicked on I/O.

## 3. UNIX Domain Socket IPC Protocol
- **Transport**: Domain socket at `/tmp/lsm_db.sock`.
- **Message Framing**: Frame length headers MUST be encoded as Protocol Buffer style unsigned varints (`varint` 1-5 bytes), NOT 4-byte big-endian fixed integers.
- **Payload Schema**:
  - Metric Name (varint length + UTF-8 string)
  - Host Name (varint length + UTF-8 string)
  - Timestamp (fixed int64)
  - Value (fixed float64)
