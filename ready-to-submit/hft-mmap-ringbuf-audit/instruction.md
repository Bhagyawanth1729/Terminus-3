# High-Frequency Trading Ring-Buffer Audit Pipeline Recovery

The multi-language limit order book (LOB) matching and compliance auditing stack under `/app` consists of a Rust lock-free matching engine and IPC ring-buffer writer (`/app/rust_engine`), a Go risk-compliance consumer daemon (`/app/go_compliance`), and a Java audit ledger service (`/app/java_audit`). Under high transaction volume and network churn, the pipeline produces corrupted order records, truncates financial balances, leaks native ring-buffer reader handles, and emits invalid JSON reports.

Your task is to repair the multi-language audit stack to satisfy all functional, concurrency, and protocol invariants:

1. **Atomic Memory Barrier Synchronization:** Ensure the IPC ring-buffer write head in `/app/rust_engine/src/ringbuf.rs` uses correct atomic memory fence ordering (`Ordering::Release`) when publishing trade payloads to shared memory (`/tmp/orderbook_ring.buf`). High-throughput market data streams consumed by `/app/go_compliance/reader.go` must read fully flushed 32-byte payload records without torn reads or corrupted 64-bit order IDs.
2. **Fixed-Point Financial Precision:** Repair fixed-point price handling in `/app/go_compliance/grpc_client.go` so 64-bit integer prices (scaled by 10^8) preserve exact decimal precision without lossy `float64` conversion when streaming trade batches over gRPC to Java.
3. **Resource Leak Recovery on Cancellation:** Ensure gRPC stream cancellations or server disconnects in `/app/go_compliance/stream_handler.go` cleanly deallocate native C-FFI ring-buffer reader handles (`C.free_reader_handle`). Active reader handle counts must remain stable under rapid client network disconnects.
4. **Locale-Independent Ledger Formatting:** Ensure `/app/java_audit/src/main/java/com/terminus/audit/AuditService.java` formats floating-point monetary values using standard US locale formatting (`.` decimal separator) so ledger output validly conforms to standard JSON float representations across all runtime environments.

All components can be compiled and executed using `/app/build_all.sh` and `/app/run_pipeline.sh`. The final audit ledger output must be written to `/app/output.json`.
