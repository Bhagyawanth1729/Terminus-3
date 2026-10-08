import os
import json
import subprocess
import pytest

OUTPUT_PATH = "/app/output.json"
JAVA_GATEWAY_BIN = "/app/java_gateway/bin"
RUST_LIB_PATH = "/app/lib"
VALIDATOR_SCRIPT = "/app/telemetry_python/validate_telemetry.py"

def test_jni_buffer_endianness_and_timestamp_accuracy():
    """Verify that JNI DirectByteBuffer byte-order endianness is correctly aligned.
    
    If Java writes big-endian integers into the buffer while Rust reads little-endian,
    departure_time (1700000000) will be byte-swapped into a corrupted numeric value.
    """
    assert os.path.exists(OUTPUT_PATH), f"Output file missing at {OUTPUT_PATH}. Has run_solution.sh executed?"
    
    with open(OUTPUT_PATH, "r") as f:
        data = json.load(f)
    
    departure_time = data.get("departure_time")
    expected_timestamp = 1700000000
    
    assert departure_time == expected_timestamp, (
        f"Endianness Mismatch Failure: departure_time expected {expected_timestamp}, got {departure_time}. "
        "Java DirectByteBuffer byte order must be aligned with Rust solver layout."
    )

def test_jni_native_handle_memory_leak():
    """Verify that native JNI VRP plan handles (jlong pointers) are deallocated after dispatch.
    
    Checks that the native handle map count drops to zero after releaseVrpPlanNative is invoked,
    preventing C-heap memory leaks during high-frequency re-routing.
    """
    assert os.path.exists(OUTPUT_PATH), f"Output file missing at {OUTPUT_PATH}."
    
    with open(OUTPUT_PATH, "r") as f:
        data = json.load(f)
    
    active_handles = data.get("active_native_handles", -1)
    
    assert active_handles == 0, (
        f"JNI Native Handle Leak Failure: active_native_handles is {active_handles}, expected 0. "
        "Native solver plan handles allocated in Rust C-heap must be deallocated via releaseVrpPlanNative."
    )

def test_locale_independent_geojson_float_parsing():
    """Verify that Java emits GeoJSON coordinates formatted with standard dot-decimal floats (Locale.US).
    
    Executes the Python telematics validator daemon to confirm that float coordinate strings parse cleanly
    without raising ValueError comma-decimal exceptions under non-US JVM locales.
    """
    assert os.path.exists(VALIDATOR_SCRIPT), f"Validator script missing at {VALIDATOR_SCRIPT}."
    
    res = subprocess.run(
        ["python3", VALIDATOR_SCRIPT, OUTPUT_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    assert res.returncode == 0, (
        f"Telematics Float Parsing Failure: Python validator returned code {res.returncode}.\n"
        f"stdout: {res.stdout}\nstderr: {res.stderr}"
    )
