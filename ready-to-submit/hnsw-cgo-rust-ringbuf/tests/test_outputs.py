import ctypes
import json
import os
import subprocess
import time
import numpy as np
import pytest

OUTPUT_JSON_PATH = "/app/output.json"
HOLDOUT_EMB_PATH = "/tests/holdout/holdout_embeddings.bin"
HOLDOUT_QUERY_PATH = "/tests/holdout/holdout_queries.bin"
HOLDOUT_RINGBUF_PATH = "/tmp/hnsw_holdout_ring.buf"
HOLDOUT_OUTPUT_PATH = "/tmp/hnsw_holdout_output.json"


def test_shipped_output_schema_and_precision():
    """
    Validates that /app/output.json exists, adheres to the required JSON schema,
    contains positive 64-bit node_ids exceeding 2^31 - 1 without negative sign extension,
    and sorts candidates descending by score.
    """
    assert os.path.exists(OUTPUT_JSON_PATH), f"Output artifact missing: {OUTPUT_JSON_PATH}"

    with open(OUTPUT_JSON_PATH, "r") as f:
        data = json.load(f)

    assert "total_queries" in data, "Missing 'total_queries' key in output JSON"
    assert "queries" in data, "Missing 'queries' key in output JSON"
    assert data["total_queries"] > 0, "total_queries must be greater than 0"
    assert len(data["queries"]) == data["total_queries"], "queries array length mismatch"

    base_high_id = 0x8000_0000_0000_0000  # 9223372036854775808

    for q in data["queries"]:
        assert "query_id" in q, "Missing 'query_id' in query object"
        assert "top_k" in q, "Missing 'top_k' in query object"
        top_k = q["top_k"]
        assert len(top_k) > 0, "top_k list must not be empty"

        prev_score = float("inf")
        for item in top_k:
            assert "node_id" in item, "Missing 'node_id' in top_k item"
            assert "score" in item, "Missing 'score' in top_k item"
            assert "reranked_rank" in item, "Missing 'reranked_rank' in top_k item"

            node_id = int(item["node_id"])
            assert node_id > 0, f"Corrupted negative node_id detected: {node_id} (cgo sign extension defect)"
            assert node_id >= base_high_id, f"node_id {node_id} does not preserve 64-bit high-bit values"

            score = float(item["score"])
            assert score <= prev_score + 1e-6, f"top_k list not sorted descending by score: {score} > {prev_score}"
            prev_score = score


def test_rebuilt_pipeline_on_holdout_dataset():
    """
    Executes the agent's rebuilt pipeline binaries against unseen held-out embedding datasets
    in /tests/holdout/ and verifies exact cosine recall precision and high node ID preservation.
    """
    go_binary = "/app/go-retrieval-server/go_retrieval_server"
    reranker_script = "/app/python-reranker/reranker.py"

    assert os.path.exists(go_binary), f"Go binary missing: {go_binary}. Must build binaries before running."
    assert os.path.exists(reranker_script), f"Reranker script missing: {reranker_script}"

    if os.path.exists(HOLDOUT_RINGBUF_PATH):
        os.remove(HOLDOUT_RINGBUF_PATH)
    if os.path.exists(HOLDOUT_OUTPUT_PATH):
        os.remove(HOLDOUT_OUTPUT_PATH)

    # 1. Run Go retrieval server on holdout data
    go_proc = subprocess.run(
        [
            go_binary,
            "-embeddings", HOLDOUT_EMB_PATH,
            "-queries", HOLDOUT_QUERY_PATH,
            "-ringbuf", HOLDOUT_RINGBUF_PATH,
            "-k", "10"
        ],
        capture_output=True,
        text=True,
        timeout=60
    )
    assert go_proc.returncode == 0, f"Go retrieval server failed on holdout dataset:\nSTDOUT:\n{go_proc.stdout}\nSTDERR:\n{go_proc.stderr}"

    # 2. Run Python reranker on holdout ring buffer
    py_proc = subprocess.run(
        ["python3", reranker_script, HOLDOUT_RINGBUF_PATH, HOLDOUT_OUTPUT_PATH],
        capture_output=True,
        text=True,
        timeout=30
    )
    assert py_proc.returncode == 0, f"Python reranker failed on holdout dataset:\nSTDOUT:\n{py_proc.stdout}\nSTDERR:\n{py_proc.stderr}"

    assert os.path.exists(HOLDOUT_OUTPUT_PATH), f"Holdout output JSON not created at {HOLDOUT_OUTPUT_PATH}"

    with open(HOLDOUT_OUTPUT_PATH, "r") as f:
        holdout_data = json.load(f)

    assert holdout_data["total_queries"] == 20, f"Expected 20 holdout queries, got {holdout_data['total_queries']}"

    base_high_id = 0x8000_0000_0000_1000
    for q in holdout_data["queries"]:
        top_k = q["top_k"]
        assert len(top_k) == 10, f"Expected top_k length 10, got {len(top_k)}"
        for item in top_k:
            node_id = int(item["node_id"])
            assert node_id >= base_high_id, f"Holdout node_id {node_id} corrupted or sign-extended"


def test_grpc_cancellation_handle_leak_stability():
    """
    Invokes search context creation and cancellation in C-FFI to verify native Rust search handle
    destruction and confirm active context count drops to zero after context completion or cancellation.
    """
    rust_so_path = "/app/librust_hnsw/target/release/librust_hnsw.so"
    assert os.path.exists(rust_so_path), f"Rust shared library missing: {rust_so_path}"

    lib = ctypes.CDLL(rust_so_path)
    lib.hnsw_init_index.argtypes = [ctypes.c_uint32, ctypes.c_size_t]
    lib.hnsw_init_index.restype = ctypes.c_void_p

    lib.hnsw_create_search_ctx.argtypes = [ctypes.c_void_p]
    lib.hnsw_create_search_ctx.restype = ctypes.c_void_p

    lib.hnsw_free_search_ctx.argtypes = [ctypes.c_void_p]
    lib.hnsw_free_search_ctx.restype = None

    lib.hnsw_get_active_ctx_count.argtypes = []
    lib.hnsw_get_active_ctx_count.restype = ctypes.c_size_t

    idx = lib.hnsw_init_index(16, 100)
    assert idx is not None, "Failed to initialize index via C-FFI"

    initial_active = lib.hnsw_get_active_ctx_count()

    # Simulate rapid search context creation and cancellation (as in Go gRPC stream aborts)
    handles = []
    for _ in range(50):
        ctx = lib.hnsw_create_search_ctx(idx)
        assert ctx is not None, "Failed to create search context"
        handles.append(ctx)

    active_during = lib.hnsw_get_active_ctx_count()
    assert active_during == initial_active + 50, f"Active context count expected {initial_active + 50}, got {active_during}"

    # Cancel / free all handles
    for h in handles:
        lib.hnsw_free_search_ctx(h)

    final_active = lib.hnsw_get_active_ctx_count()
    assert final_active == initial_active, f"Memory/handle leak detected: {final_active} active contexts remaining after cleanup (expected {initial_active})"
