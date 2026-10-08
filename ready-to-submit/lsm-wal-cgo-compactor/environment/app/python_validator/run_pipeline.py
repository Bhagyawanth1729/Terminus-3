import json
import os
import glob
import re
import sys
from client import fetch_ipc_records

def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x82F63B78
            else:
                crc >>= 1
    return (~crc) & 0xFFFFFFFF

def verify_and_aggregate(sst_dir="/app/sst", socket_path="/tmp/lsm_db.sock", output_file="/app/output.json"):
    sst_files = sorted(glob.glob(os.path.join(sst_dir, "*.sst")))
    sst_summaries = []

    for fpath in sst_files:
        with open(fpath, "rb") as f:
            content = f.read()

        lines = content.split(b"\n", 3)
        if len(lines) < 4:
            continue

        magic = lines[0].decode('utf-8', errors='ignore').strip()
        len_line = lines[1].decode('utf-8', errors='ignore').strip()
        crc_line = lines[2].decode('utf-8', errors='ignore').strip()
        raw_payload = lines[3]

        expected_crc = int(crc_line.split(":")[1], 16) if ":" in crc_line else 0
        actual_crc = crc32c(raw_payload)

        sst_summaries.append({
            "filename": os.path.basename(fpath),
            "magic": magic,
            "expected_crc": f"{expected_crc:08x}",
            "actual_crc": f"{actual_crc:08x}",
            "crc_valid": expected_crc == actual_crc
        })

    records = fetch_ipc_records(socket_path)

    metrics_summary = {}
    host_set = set()

    for r in records:
        m = r["metric"]
        h = r["host"]
        v = r["value"]

        host_set.add(h)
        if m not in metrics_summary:
            metrics_summary[m] = {"count": 0, "sum": 0.0, "min": v, "max": v}

        metrics_summary[m]["count"] += 1
        metrics_summary[m]["sum"] += v
        if v < metrics_summary[m]["min"]:
            metrics_summary[m]["min"] = v
        if v > metrics_summary[m]["max"]:
            metrics_summary[m]["max"] = v

    for m in metrics_summary:
        metrics_summary[m]["avg"] = round(metrics_summary[m]["sum"] / metrics_summary[m]["count"], 4)
        metrics_summary[m]["sum"] = round(metrics_summary[m]["sum"], 4)

    output = {
        "sst_files_count": len(sst_files),
        "sst_crc_valid_count": sum(1 for s in sst_summaries if s["crc_valid"]),
        "sst_details": sst_summaries,
        "total_records": len(records),
        "unique_hosts_count": len(host_set),
        "metrics_summary": metrics_summary
    }

    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, sort_keys=True)

    print(f"Pipeline executed successfully. Output written to {output_file}")

if __name__ == "__main__":
    sst_dir = sys.argv[1] if len(sys.argv) > 1 else "/app/sst"
    sock_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/lsm_db.sock"
    out_file = sys.argv[3] if len(sys.argv) > 3 else "/app/output.json"
    verify_and_aggregate(sst_dir, sock_path, out_file)
