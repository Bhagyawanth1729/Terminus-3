import subprocess
import time
import sys
import os
from client import FlightClient

def main():
    print("Testing Arrow Flight C-FFI Microservice...")
    server_proc = None
    server_bin = "/app/flight-server/flight-server"
    
    if os.path.exists(server_bin):
        print("Launching background flight-server process...")
        server_proc = subprocess.Popen([server_bin], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)

    client = FlightClient()

    try:
        print("\n--- Test 1: Active Threads Check ---")
        m1 = client.metrics()
        print(f"Metrics: {m1}")

        print("\n--- Test 2: Standard Query Execution ---")
        res = client.query(query_id=101, batches=5)
        print(f"Query Result: {res}")
        if "exact_string" in res and res["exact_string"]:
            print(f"SUCCESS: Exact Decimal128: {res['exact_string']}")
        else:
            print("WARNING: Precision lost! 'exact_string' missing or empty.")

        print("\n--- Test 3: Short Timeout / Cancellation Check ---")
        # Run query with timeout shorter than execution
        c_res = client.query(query_id=102, batches=20, timeout=0.2)
        print(f"Cancellation Result: {c_res}")

        time.sleep(1.5)
        m2 = client.metrics()
        print(f"Metrics after cancellation: {m2}")
        if m2.get("active_threads", 0) > 0:
            print("WARNING: Tokio worker threads leaked! Active threads > 0 after cancellation.")

    finally:
        if server_proc:
            server_proc.terminate()
            server_proc.wait()

if __name__ == "__main__":
    main()
