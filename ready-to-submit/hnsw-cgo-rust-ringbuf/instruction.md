The hybrid vector retrieval pipeline located in `/app` is failing integration benchmarks. The architecture consists of a Go query server (`/app/go-retrieval-server`), a native Rust C-FFI HNSW vector search module (`/app/librust_hnsw`), and a Python IPC re-ranking sidecar (`/app/python-reranker`). The service processes input query vectors, retrieves top candidate matches from the HNSW index, exchanges payloads over a lock-free IPC ring buffer (`/tmp/hnsw_ring.buf`), and emits final re-ranked matches. Technical specifications and structural layout are documented in `/app/spec/hnsw_ipc_spec.md`.

Diagnose and repair all execution defects across the Go, Rust, and Python boundary so the retrieval pipeline operates correctly and passes validation checks:

- Ensure vector candidate node IDs across the entire range ($0 \le \text{ID} < 2^{64}$) are preserved without truncation or negative value sign corruption during cgo retrieval.
- Fix lock-free IPC ring buffer synchronization in `/tmp/hnsw_ring.buf` to eliminate payload corruption and torn reads during concurrent query re-ranking.
- Resolve search context handle leaks when gRPC queries or client streams are aborted mid-execution.
- Ensure the pipeline can be cleanly built using `/app/build_and_run.sh` and produces accurate re-ranked retrieval results at `/app/output.json`.

The output JSON file at `/app/output.json` must strictly adhere to the following schema:
```json
{
  "total_queries": 100,
  "queries": [
    {
      "query_id": 0,
      "top_k": [
        {
          "node_id": 18446744073709551600,
          "score": 0.9845,
          "reranked_rank": 1
        }
      ]
    }
  ]
}
```
All top-k list entries within `/app/output.json` must be sorted in descending order by `score` and contain valid `node_id` strings or numbers matching the reference embeddings.
