# HNSW IPC & C-FFI Technical Specification

## Overview
The hybrid vector retrieval pipeline comprises three components communicating across language boundaries:
1. **Rust Core (`librust_hnsw`)**: Implements C-FFI functions for vector search and lock-free IPC ring buffer writing.
2. **Go Query Server (`go-retrieval-server`)**: Binds to `librust_hnsw` via cgo, traverses index candidates, and streams search results to shared memory.
3. **Python Reranker (`python-reranker`)**: Reads candidate vector matches from `/tmp/hnsw_ring.buf`, performs cosine similarity re-ranking, and outputs final JSON results.

## C-FFI Layout & Types
Headers are declared in `include/hnsw_cffi.h`:
```c
typedef struct {
    uint64_t node_id;   // 64-bit vector node identifier
    float distance;     // Cosine distance score
} hnsw_result_c;
```

`node_id` represents an unsigned 64-bit vector ID (ranging from 0 up to $2^{64}-1$).

## Lock-Free IPC Ring Buffer Spec
Memory region is located at `/tmp/hnsw_ring.buf`.
Header layout (32 bytes):
- `magic`: 0x484E5357 (ASCII "HNSW")
- `capacity`: Maximum number of slots (default 1024)
- `item_size`: Fixed size of each slot payload (128 bytes)
- `write_head`: 32-bit atomic sequence index
- `read_head`: 32-bit atomic sequence index

Slot Payload Layout (128 bytes):
- `query_id`: uint32
- `node_id`: uint64
- `distance`: float32
- `vector_dim`: uint32 (e.g. 16)
- `vector_data`: array of 16 float32 values (64 bytes)
- `reserved`: padding bytes to 128 bytes

Atomic sequence updates must enforce Release ordering on write head updates to guarantee payload memory stores are visible across process memory boundaries before sequence indices advance.

## Query Context Lifecycle
Every search stream creates a native `SearchContext` handle via `hnsw_create_search_ctx`. Native context resources must be released via `hnsw_free_search_ctx` upon query completion or client stream cancellation.
