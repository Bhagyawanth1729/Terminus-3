The multi-language tensor inference pipeline in `/app` is failing integration and stress tests. The system receives quantized tensor inference requests through a Go ingress gateway (`/app/go-ingress`), streams payloads through a POSIX shared-memory ring buffer (`/dev/shm/tensor_ringbuf.shm`), executes SIMD matrix multiplication in a native Rust kernel library (`/app/rust-engine`), and coordinates dynamic batching and request cleanup in Python (`/app/python-orchestrator`).

Diagnose and resolve the following issues across the codebase:

- The Go ingress gateway incorrectly computes memory offsets and serializes quantization scale factors when writing tensor slots into `/dev/shm/tensor_ringbuf.shm`, leading to alignment faults and corrupted logit outputs in downstream consumers.
- The Python dynamic batch orchestrator fails to properly clean up and advance shared memory ring buffer atomic pointers when handling dropped or timed-out client requests, causing the ring buffer to deadlock under concurrent load.
- Ensure all components compile cleanly via `/app/build_all.sh` and that the Go ingress server (`/app/go-ingress/ingress-server`) responds correctly on port `50052` to `/infer` requests with status `SUCCESS` and bit-exact `logits` vectors.
