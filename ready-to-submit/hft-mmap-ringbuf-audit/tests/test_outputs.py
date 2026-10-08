import json
import os
import subprocess
import pytest

def test_sample_output_correctness():
    output_path = "/app/output.json"
    assert os.path.exists(output_path), f"Output file missing: {output_path}"

    with open(output_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("status") == "SUCCESS", f"Expected SUCCESS status, got {data.get('status')}"
    assert data.get("total_trades") == 1000, f"Expected 1000 trades, got {data.get('total_trades')}"
    assert data.get("total_volume_scaled") == 1502500000000, f"Expected 1502500000000 volume scaled, got {data.get('total_volume_scaled')}"
    assert data.get("average_price") == "150.2500", f"Expected average_price '150.2500', got '{data.get('average_price')}'"

def test_holdout_pipeline_rerun():
    holdout_ticks = "/tests/holdout/ticks_holdout.bin"
    assert os.path.exists(holdout_ticks), f"Holdout tick dataset missing: {holdout_ticks}"

    out_json = "/tmp/holdout_out.json"

    # Rebuild from agent source
    res_build = subprocess.run(["/bin/bash", "/app/build_all.sh"], capture_output=True, text=True)
    assert res_build.returncode == 0, f"Rebuild failed: {res_build.stderr}\n{res_build.stdout}"

    # Run pipeline on holdout
    res_run = subprocess.run(["/bin/bash", "/app/run_pipeline.sh", holdout_ticks, out_json, "5000"], capture_output=True, text=True)
    assert res_run.returncode == 0, f"Holdout pipeline execution failed: {res_run.stderr}\n{res_run.stdout}"

    assert os.path.exists(out_json), f"Holdout output file missing: {out_json}"

    with open(out_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("status") == "SUCCESS"
    assert data.get("total_trades") == 5000, f"Expected 5000 holdout trades, got {data.get('total_trades')}"
    assert data.get("total_volume_scaled") == 30725000000000, f"Expected 30725000000000 volume, got {data.get('total_volume_scaled')}"
    assert data.get("average_price") == "245.8000", f"Expected average_price '245.8000', got '{data.get('average_price')}'"

def test_atomic_memory_release_ordering():
    rust_src = "/app/rust_engine/src/ringbuf.rs"
    assert os.path.exists(rust_src), f"Rust source missing: {rust_src}"

    with open(rust_src, "r", encoding="utf-8") as f:
        content = f.read()

    assert "header.head.store(head + 1, Ordering::Release)" in content or "header.head.store(head + 1, Ordering::SeqCst)" in content, \
        "Rust ring buffer write head update must use Ordering::Release or Ordering::SeqCst to prevent store reordering."

def test_reader_handle_leak_on_cancel():
    go_src = "/app/go_compliance/stream_handler.go"
    assert os.path.exists(go_src), f"Go stream handler source missing: {go_src}"

    with open(go_src, "r", encoding="utf-8") as f:
        content = f.read()

    assert "reader.Free()" in content or "C.free_reader_handle" in content, \
        "Go stream processor must invoke reader.Free() / C.free_reader_handle on all code paths / defer to prevent reader handle leaks."

def test_locale_formatting_robustness():
    java_src = "/app/java_audit/src/main/java/com/terminus/audit/AuditService.java"
    assert os.path.exists(java_src), f"Java audit source missing: {java_src}"

    with open(java_src, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Locale.US" in content, "Java AuditService must explicitly specify Locale.US in String.format to guarantee dot-decimal formatting."
