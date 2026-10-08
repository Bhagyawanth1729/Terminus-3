import sys
import json
import os

def validate_dispatch(output_path="/app/output.json"):
    if not os.path.exists(output_path):
        print(f"Error: Output file not found at {output_path}")
        return False

    try:
        with open(output_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON output: {e}")
        return False

    print("Validating dispatch telemetry output...")
    
    # Check 1: Departure timestamp precision (Endianness check)
    departure_time = data.get("departure_time")
    expected_timestamp = 1700000000
    if departure_time != expected_timestamp:
        print(f"FAIL: Departure timestamp corruption! Expected {expected_timestamp}, got {departure_time}")
        return False
    print("PASS: Departure timestamp matches exact value (Endianness aligned).")

    # Check 2: Float coordinate parsing (Locale check)
    try:
        lat = float(data.get("latitude", ""))
        lon = float(data.get("longitude", ""))
    except ValueError as e:
        print(f"FAIL: Float coordinate parsing failed: {e}")
        return False
    print(f"PASS: Coordinate floats parsed cleanly: lat={lat}, lon={lon}")

    # Check 3: Active native handle leak check
    active_handles = data.get("active_native_handles", -1)
    if active_handles != 0:
        print(f"FAIL: Native JNI handle leak detected! Active handles: {active_handles}")
        return False
    print("PASS: Native JNI handle count is 0 (Zero heap leaks).")

    print("ALL TELEMETRY VALIDATIONS PASSED.")
    return True

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "/app/output.json"
    success = validate_dispatch(path)
    sys.exit(0 if success else 1)
