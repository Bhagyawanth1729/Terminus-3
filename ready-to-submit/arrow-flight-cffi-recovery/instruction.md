# Arrow Flight C-FFI Microservice Recovery

The high-throughput analytical query microservice under `/app/` consists of a Python client application, a Go Arrow Flight server orchestration layer (`/app/flight-server`), and an embedded Rust vector execution engine (`/app/libarrow_exec`). The service is currently unstable under production workloads and produces incorrect analytical results.

Your task is to repair the service to achieve full operational correctness:
1. **Context Cancellation & Resource Cleanup:** When clients abort or time out on Flight stream requests, all downstream execution resources must be freed immediately. Query cancellations must notify the underlying Rust vector engine, terminating background Tokio worker threads and releasing mutex locks cleanly without leaving shared handles in a poisoned state or leaking background threads.
2. **Post-Cancellation System Recovery:** The service must remain fully operational and serve subsequent analytical queries immediately following client stream cancellations.
3. **Decimal Precision Integrity:** Fixed-point Decimal128 schema metadata and values passed from the Rust engine through the Go Flight server to Python clients must maintain exact 128-bit decimal precision without undergoing lossy floating-point conversions.

All components can be built and tested locally using `/app/build_all.sh` and `/app/client/run_demo.py`.
