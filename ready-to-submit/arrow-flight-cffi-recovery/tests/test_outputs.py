import os
import time
import subprocess
import urllib.request
import urllib.error
import json
import pytest

SERVER_BIN = "/app/flight-server/flight-server"
SERVER_URL = "http://127.0.0.1:50051"

@pytest.fixture(scope="module", autouse=True)
def flight_server():
    """Ensure server is running for tests, then terminate after."""
    if not os.path.exists(SERVER_BIN):
        pytest.fail(f"Flight server binary not found at {SERVER_BIN}. Has build_all.sh been run?")
    
    proc = subprocess.Popen([SERVER_BIN], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1.5)
    
    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()

def http_get(endpoint, timeout=5):
    url = f"{SERVER_URL}{endpoint}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}

def test_decimal128_exact_precision():
    """Verify Decimal128 schema metadata and exact integer representation are preserved without float loss."""
    res = http_get("/query?id=500&batches=10", timeout=5)
    assert res.get("status") == "SUCCESS", f"Query failed: {res}"
    
    assert "exact_string" in res, "Decimal128 exact_string is missing from server response"
    assert res["exact_string"] != "", "Decimal128 exact_string must not be empty"
    
    # 10 batches -> high = 100, low = 10 * 1000000000000000000 = 10000000000000000000
    expected_high = 100
    expected_low = 10_000_000_000_000_000_000
    
    assert res.get("decimal_high") == expected_high, f"Expected decimal_high={expected_high}, got {res.get('decimal_high')}"
    assert res.get("decimal_low") == expected_low, f"Expected decimal_low={expected_low}, got {res.get('decimal_low')}"
    assert res["exact_string"] == f"{expected_high}:{expected_low}", f"Unexpected exact_string: {res['exact_string']}"

def test_cancellation_no_thread_leak():
    """Verify client context cancellations trigger C-FFI cancel and halt Tokio worker threads."""
    # Issue 5 rapid queries that time out quickly
    for i in range(5):
        try:
            http_get(f"/query?id={700+i}&batches=20", timeout=0.1)
        except Exception:
            pass

    time.sleep(1.2)

    # Check metrics for active Tokio worker threads
    metrics = http_get("/metrics", timeout=5)
    active_threads = metrics.get("active_threads", -1)
    
    assert active_threads == 0, f"Tokio worker threads leaked after query cancellation! Active threads: {active_threads}"

def test_post_cancellation_system_recovery():
    """Verify system remains responsive and C-FFI mutexes are not left poisoned after cancellation."""
    res = http_get("/query?id=800&batches=5", timeout=5)
    assert res.get("status") == "SUCCESS", f"System failed to recover post-cancellation (possible poisoned lock): {res}"
    assert res.get("decimal_high") == 50, f"Unexpected high result post-cancellation: {res}"
