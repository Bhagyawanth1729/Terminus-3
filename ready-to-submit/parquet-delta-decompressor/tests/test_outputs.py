import json
import os
import subprocess
import pytest


def test_golden_report_schema_and_values():
    """Verify that /app/out/report.json exists and contains correct schema and values for primary dataset."""
    report_path = "/app/out/report.json"
    assert os.path.exists(report_path), f"Output report missing at {report_path}"

    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Required schema keys
    required_keys = [
        "total_records",
        "min_timestamp",
        "max_timestamp",
        "negative_delta_count",
        "mean_delta_ms",
        "status_counts",
    ]
    for key in required_keys:
        assert key in data, f"Missing required field '{key}' in report JSON"

    # Value type assertions
    assert isinstance(data["total_records"], int)
    assert isinstance(data["min_timestamp"], int)
    assert isinstance(data["max_timestamp"], int)
    assert isinstance(data["negative_delta_count"], int)
    assert isinstance(data["mean_delta_ms"], (int, float))
    assert isinstance(data["status_counts"], dict)

    # Numerical accuracy assertions for primary dataset (1000 deltas + 1 initial = 1001 records)
    assert data["total_records"] == 1001, f"Expected 1001 records, got {data['total_records']}"
    assert data["min_timestamp"] == 1700000000000, f"Expected min timestamp 1700000000000, got {data['min_timestamp']}"
    assert data["negative_delta_count"] == 300, f"Expected 300 negative deltas, got {data['negative_delta_count']}"

    # Status tag dictionary frequency assertions
    expected_status_counts = {
        "ERR_TIMEOUT": 50,
        "STATUS_OK": 50,
        "WARN_LATENCY": 50,
    }
    assert data["status_counts"] == expected_status_counts, (
        f"Expected status_counts {expected_status_counts}, got {data['status_counts']}"
    )


def test_holdout_edge_telemetry():
    """Re-run query_pipeline.py against held-out edge dataset containing 250 dictionary entries and 450 negative deltas."""
    holdout_data = "/tests/holdout/edge_telemetry.parquet"
    out_json = "/work/out/holdout_report.json"
    os.makedirs(os.path.dirname(out_json), exist_ok=True)

    # Rebuild native library if agent modified Rust code
    if os.path.exists("/app/build.sh"):
        subprocess.run(["/bin/bash", "/app/build.sh"], check=True)

    cmd = ["python3", "/app/src/query_pipeline.py", "--data", holdout_data, "--out", out_json]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Pipeline execution failed on holdout dataset:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"

    assert os.path.exists(out_json), "Holdout output report not generated"
    with open(out_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Assert holdout dataset values (1500 deltas + 1 initial = 1501 records)
    assert data["total_records"] == 1501, f"Holdout total records expected 1501, got {data['total_records']}"
    assert data["negative_delta_count"] == 600, f"Holdout negative delta count expected 600, got {data['negative_delta_count']}"
    assert data["min_timestamp"] == 1800000000000

    expected_holdout_counts = {
        "CRIT_DISK_FULL": 62,
        "ERR_TIMEOUT": 62,
        "STATUS_OK": 63,
        "WARN_LATENCY": 63,
    }
    assert data["status_counts"] == expected_holdout_counts, (
        f"Expected holdout status_counts {expected_holdout_counts}, got {data['status_counts']}"
    )


def test_determinism_and_buffer_integrity():
    """Run pipeline twice on primary dataset and assert byte-identical output JSON."""
    out_run1 = "/work/out/run1.json"
    out_run2 = "/work/out/run2.json"
    data_path = "/app/data/telemetry.parquet"

    if not os.path.exists(data_path):
        data_path = "/tests/holdout/edge_telemetry.parquet"

    cmd1 = ["python3", "/app/src/query_pipeline.py", "--data", data_path, "--out", out_run1]
    cmd2 = ["python3", "/app/src/query_pipeline.py", "--data", data_path, "--out", out_run2]

    res1 = subprocess.run(cmd1, capture_output=True, text=True)
    res2 = subprocess.run(cmd2, capture_output=True, text=True)

    assert res1.returncode == 0, f"Run 1 failed: {res1.stderr}"
    assert res2.returncode == 0, f"Run 2 failed: {res2.stderr}"

    with open(out_run1, "rb") as f1, open(out_run2, "rb") as f2:
        content1 = f1.read()
        content2 = f2.read()

    assert content1 == content2, "Pipeline output is non-deterministic across consecutive runs"
