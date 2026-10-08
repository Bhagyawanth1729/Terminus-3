# High-Frequency Trading Ring-Buffer & Audit Protocol Specification

## 1. Shared Memory IPC Ring Buffer Format (`/tmp/orderbook_ring.buf`)

The IPC ring buffer header and payload layout is structured as follows:

- Header (64 bytes):
  - `magic` (4 bytes): `0x48465431` ("HFT1")
  - `capacity` (4 bytes): Number of 32-byte slots (default 1024)
  - `head` (8 bytes atomic uint64): Write sequence index (monotonically increasing)
  - `tail` (8 bytes atomic uint64): Read sequence index (monotonically increasing)
  - `reserved` (40 bytes): Padding

- Slot Payload Layout (32 bytes per trade record):
  - `order_id` (8 bytes uint64, Little Endian): Monotonic 64-bit trade identifier
  - `price_scaled` (8 bytes int64, Little Endian): Scaled integer price ($10^8$ fixed-point scale factor)
  - `quantity` (8 bytes uint64, Little Endian): Shares/units traded
  - `timestamp_ns` (8 bytes uint64, Little Endian): Nanosecond timestamp

## 2. Memory Order & Concurrency Invariants

- **Write Barrier**: The producer (Rust engine) MUST issue a Release memory fence (`Ordering::Release`) when advancing `head` after writing slot bytes.
- **Read Barrier**: The consumer (Go reader) MUST issue an Acquire memory fence when reading `head` before consuming slot bytes.
- **Torn Reads**: Incomplete payload writes due to relaxed memory stores invalidate order ID integrity and trigger audit checksum failures.

## 3. Financial Precision Invariants

- All monetary calculations must maintain exact $10^8$ fixed-point integer scaling (`price_scaled`).
- Casting `price_scaled` to double-precision float (`float64`) prior to batch aggregation corrupts trailing decimal places on institutional trade sizes.

## 4. Resource Allocation & Cleanup

- Native reader handles allocated via `create_reader_handle()` MUST be released via `free_reader_handle()` upon gRPC stream completion or error.

## 5. Audit Report Schema (`/app/output.json`)

Output JSON format:
```json
{
  "status": "SUCCESS",
  "total_trades": 1000,
  "total_volume_scaled": 1502500000000,
  "average_price": "150.2500"
}
```
`average_price` MUST be formatted using standard US locale formatting (`.` decimal separator).
