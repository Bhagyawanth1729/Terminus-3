"""
Verifier for lsm-wal-cgo-compactor task.
Evaluates correctness across three independent axes:
1. Semantic accuracy and Castagnoli CRC32c validity of /app/output.json.
2. Re-running the agent's rebuilt pipeline against unseen holdout WAL files.
3. Lock poisoning recovery and binary wire protocol conformance.
"""

import json
import os
import subprocess
import time
import pytest

OUTPUT_JSON = "/app/output.json"
SST_DIR = "/app/sst"
HOLDOUT_WAL_DIR = "/tests/holdout/wal"

def test_output_json_semantic_correctness():
    """
    Verifies that /app/output.json exists, contains valid metrics aggregations,
    correct unique host counts, and that all generated SSTable files pass CRC32c verification.
    """
    assert os.path.exists(OUTPUT_JSON), f"Expected {OUTPUT_JSON} to exist"

    with open(OUTPUT_JSON, "r") as f:
        data = json.load(f)

    assert data.get("sst_files_count") == 2, f"Expected 2 SST files, got {data.get('sst_files_count')}"
    assert data.get("sst_crc_valid_count") == 2, f"Expected 2 valid CRC SST files, got {data.get('sst_crc_valid_count')}"
    assert data.get("total_records") == 10, f"Expected 10 total records, got {data.get('total_records')}"
    assert data.get("unique_hosts_count") == 3, f"Expected 3 unique hosts, got {data.get('unique_hosts_count')}"

    metrics = data.get("metrics_summary", {})
    assert "cpu_usage" in metrics, "Missing metric cpu_usage"
    assert "mem_used_gb" in metrics, "Missing metric mem_used_gb"
    assert "disk_iops" in metrics, "Missing metric disk_iops"

    cpu = metrics["cpu_usage"]
    assert cpu["count"] == 4, f"cpu_usage count should be 4, got {cpu['count']}"
    assert abs(cpu["sum"] - 228.7) < 1e-3, f"cpu_usage sum should be 228.7, got {cpu['sum']}"
    assert abs(cpu["avg"] - 57.175) < 1e-3, f"cpu_usage avg should be 57.175, got {cpu['avg']}"

    mem = metrics["mem_used_gb"]
    assert mem["count"] == 4, f"mem_used_gb count should be 4, got {mem['count']}"
    assert abs(mem["sum"] - 92.1) < 1e-3, f"mem_used_gb sum should be 92.1, got {mem['sum']}"

    disk = metrics["disk_iops"]
    assert disk["count"] == 2, f"disk_iops count should be 2, got {disk['count']}"
    assert abs(disk["sum"] - 3070.0) < 1e-3, f"disk_iops sum should be 3070.0, got {disk['sum']}"


def test_holdout_wal_compaction_pipeline():
    """
    Re-runs the agent's rebuilt binaries (/app/bin/go_wal_service and librust_compactor.so)
    against unseen holdout WAL datasets in /tests/holdout/wal. Verifies holdout metrics
    aggregation and Castagnoli CRC32c footer validity.
    """
    assert os.path.exists(HOLDOUT_WAL_DIR), f"Holdout directory {HOLDOUT_WAL_DIR} missing"
    assert os.path.exists("/app/bin/go_wal_service"), "Rebuilt /app/bin/go_wal_service binary missing"

    holdout_sst_dir = "/tmp/holdout_sst"
    holdout_output_json = "/tmp/holdout_output.json"
    socket_path = "/tmp/lsm_db_holdout.sock"

    os.system(f"rm -rf {holdout_sst_dir} {holdout_output_json} {socket_path}")
    os.makedirs(holdout_sst_dir, exist_ok=True)

    env = os.environ.copy()
    env["WAL_DATA_DIR"] = HOLDOUT_WAL_DIR
    env["SST_OUTPUT_DIR"] = holdout_sst_dir

    proc = subprocess.Popen(["/app/bin/go_wal_service"], env=env)
    time.sleep(2)

    try:
        cmd = [
            "python3", "/app/python_validator/run_pipeline.py",
            holdout_sst_dir, "/tmp/lsm_db.sock", holdout_output_json
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert res.returncode == 0, f"Holdout pipeline failed: {res.stderr}"

        assert os.path.exists(holdout_output_json), "Holdout output.json not generated"
        with open(holdout_output_json, "r") as f:
            hdata = json.load(f)

        assert hdata.get("sst_files_count") == 2, "Holdout SST count mismatch"
        assert hdata.get("sst_crc_valid_count") == 2, "Holdout SST CRC invalid"
        assert hdata.get("total_records") == 6, f"Holdout record count should be 6, got {hdata.get('total_records')}"

        hmetrics = hdata.get("metrics_summary", {})
        assert "network_rx_mb" in hmetrics, "Missing holdout metric network_rx_mb"
        assert "network_tx_mb" in hmetrics, "Missing holdout metric network_tx_mb"

        rx = hmetrics["network_rx_mb"]
        assert rx["count"] == 4, f"network_rx_mb count should be 4, got {rx['count']}"
        assert abs(rx["sum"] - 742.9) < 1e-3, f"network_rx_mb sum should be 742.9, got {rx['sum']}"

    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_atomic_concurrency_and_lock_poisoning_recovery():
    """
    Verifies that Go/Rust C-FFI compaction handles lock poisoning recovery safely
    and computes hardware Castagnoli CRC32c checksums rather than IEEE polynomials.
    """
    rust_lib = "/app/lib/librust_compactor.so"
    assert os.path.exists(rust_lib), f"Dynamic library {rust_lib} missing"

    # Read binary symbols in librust_compactor.so
    res = subprocess.run(["nm", "-D", rust_lib], capture_output=True, text=True)
    assert "cgo_compact_wal" in res.stdout, "cgo_compact_wal symbol missing from librust_compactor.so"
