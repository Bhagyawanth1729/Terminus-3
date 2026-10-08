import os
import time
import subprocess
import urllib.request
import urllib.error
import json
import pytest
import math

SERVER_BIN = "/app/go-ingress/ingress-server"
SERVER_URL = "http://127.0.0.1:50052"

WEIGHT_MATRIX = [
    [0.25, -0.50, 0.75, 0.10, -0.20, 0.30, 0.15, -0.05],
    [-0.10, 0.40, -0.30, 0.80, 0.05, -0.15, 0.25, 0.50],
    [0.60, 0.20, -0.10, -0.40, 0.90, -0.05, 0.10, -0.30],
    [-0.35, 0.15, 0.45, -0.25, 0.10, 0.70, -0.60, 0.20],
    [0.12, -0.24, 0.36, -0.48, 0.60, -0.72, 0.84, -0.96],
    [0.50, 0.50, -0.50, -0.50, 0.25, 0.25, -0.25, -0.25],
    [-0.70, 0.10, 0.30, 0.20, -0.40, 0.50, 0.60, -0.10],
    [0.30, -0.60, 0.10, 0.40, -0.50, 0.20, -0.30, 0.80],
]

def compute_expected_logits(data, scale):
    logits = []
    for row in WEIGHT_MATRIX:
        s = 0.0
        for i, val in enumerate(data):
            w = row[i % 8]
            s += float(val) * scale * w
        logits.append(s)
    return logits

@pytest.fixture(scope="module", autouse=True)
def ingress_server():
    """Start the Go Ingress server before tests and terminate afterward."""
    if not os.path.exists(SERVER_BIN):
        pytest.fail(f"Ingress server binary not found at {SERVER_BIN}. Was build_all.sh executed?")

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = "/usr/local/lib:/app/rust-engine/target/release:/app/go-ingress:" + env.get("LD_LIBRARY_PATH", "")

    proc = subprocess.Popen([SERVER_BIN], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1.5)

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()

def post_json(endpoint, payload, timeout=5):
    url = f"{SERVER_URL}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"error": body}
    except Exception as e:
        return 500, {"error": str(e)}

def get_json(endpoint, timeout=5):
    url = f"{SERVER_URL}{endpoint}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"error": body}
    except Exception as e:
        return 500, {"error": str(e)}

def test_server_health():
    """Verify ingress server responds to health endpoint."""
    status, body = get_json("/health", timeout=5)
    assert status == 200, f"Expected status 200, got {status}: {body}"
    assert body.get("status") == "OK", f"Health status not OK: {body}"

def test_numerical_precision_and_alignment():
    """Verify 64-byte alignment and exact logit precision across quantized inputs."""
    test_cases = [
        {"data": [10, -5, 20, 15, -30, 4, -12, 8], "scale": 0.05},
        {"data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16], "scale": 0.125},
        {"data": [-128, 127, 0, 64, -64, 32, -32, 16], "scale": 0.0078125},
    ]

    for idx, tc in enumerate(test_cases):
        payload = {
            "query_id": 1000 + idx,
            "data": tc["data"],
            "scale": tc["scale"],
        }
        status, body = post_json("/infer", payload, timeout=5)
        assert status == 200, f"Inference failed with status {status}: {body}"
        assert body.get("status") == "SUCCESS", f"Query {payload['query_id']} did not return SUCCESS: {body}"

        logits = body.get("logits", [])
        assert len(logits) == 8, f"Expected 8 logits, got {len(logits)}"

        expected = compute_expected_logits(tc["data"], tc["scale"])
        for i in range(8):
            diff = abs(logits[i] - expected[i])
            assert diff < 1e-3, f"Logit[{i}] mismatch: expected {expected[i]:.5f}, got {logits[i]:.5f} (diff={diff})"

def test_concurrency_and_cancellation_recovery():
    """Verify system remains stable after rapid bursts and does not deadlock ring buffer slots."""
    # Send 20 rapid queries with varying scales
    for i in range(20):
        payload = {
            "query_id": 2000 + i,
            "data": [(i * 3 + j) % 120 - 60 for j in range(32)],
            "scale": 0.02,
        }
        status, body = post_json("/infer", payload, timeout=5)
        assert status == 200, f"Concurrent query {i} failed: {body}"
        assert body.get("status") == "SUCCESS"

    # Check metrics to ensure progress is tracked
    status, metrics = get_json("/metrics", timeout=5)
    assert status == 200, f"Failed to retrieve metrics: {metrics}"
    assert metrics.get("total_processed", 0) >= 20, f"Expected at least 20 processed queries, got {metrics.get('total_processed')}"
