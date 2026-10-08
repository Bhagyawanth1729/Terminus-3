import json
import os
import subprocess
import pytest

OUTPUT_JSON_PATH = "/app/output.json"
RUST_RINGBUF_PATH = "/app/rust_aligner/src/ringbuf.rs"
JAVA_SERVICE_PATH = "/app/java_gateway/src/main/java/com/terminus/genomics/SequenceStreamService.java"
PYTHON_ANNOTATOR_PATH = "/app/python_annotator/annotator.py"

def test_output_json_exists_and_valid():
    """Verify that /app/output.json exists, follows required schema, and has correct Phred score."""
    assert os.path.exists(OUTPUT_JSON_PATH), f"Output file {OUTPUT_JSON_PATH} does not exist."

    with open(OUTPUT_JSON_PATH, "r") as f:
        data = json.load(f)

    required_keys = ["total_reads_processed", "aligned_reads", "unaligned_reads", "mean_phred_score", "variants"]
    for key in required_keys:
        assert key in data, f"Missing key '{key}' in output.json"

    assert data["total_reads_processed"] > 0, "total_reads_processed should be > 0"
    assert data["aligned_reads"] > 0, "aligned_reads should be > 0"
    assert isinstance(data["variants"], list), "variants should be a list"

    # Phred Q+33 verification: ASCII 'I' (73) - 33 = 40.0.
    # If using Illumina Q+64 offset (73 - 64 = 9.0), this test fails.
    assert data["mean_phred_score"] >= 35.0, f"mean_phred_score {data['mean_phred_score']} is below Sanger Q+33 threshold (~40.0)."

def test_python_phred_calculation():
    """Verify that Python annotator source uses Sanger Q+33 offset rather than Illumina Q+64."""
    assert os.path.exists(PYTHON_ANNOTATOR_PATH), f"Python annotator script missing at {PYTHON_ANNOTATOR_PATH}."
    
    with open(PYTHON_ANNOTATOR_PATH, "r") as f:
        content = f.read()

    assert "ord(c) - 33" in content, "annotator.py must use Sanger Phred Q+33 offset: ord(c) - 33"
    assert "ord(c) - 64" not in content, "annotator.py still contains broken Illumina Q+64 offset: ord(c) - 64"

def test_rust_atomic_release_fence():
    """Verify that Rust ringbuf.rs uses Ordering::Release for atomic write_head sequence updates."""
    assert os.path.exists(RUST_RINGBUF_PATH), f"Rust ringbuf source missing at {RUST_RINGBUF_PATH}."

    with open(RUST_RINGBUF_PATH, "r") as f:
        content = f.read()

    assert "Ordering::Release" in content, "ringbuf.rs must use Ordering::Release memory barrier for atomic write_head stores."

def test_java_stream_cancellation_handle_cleanup():
    """Verify Java SequenceStreamService calls alignerDestroy on stream cancellation."""
    assert os.path.exists(JAVA_SERVICE_PATH), f"Java service missing at {JAVA_SERVICE_PATH}."

    with open(JAVA_SERVICE_PATH, "r") as f:
        content = f.read()

    assert "NativeAlignerBridge.alignerDestroy(alignerPtr);" in content, "SequenceStreamService must invoke alignerDestroy on stream cancellation."

def test_holdout_execution():
    """Re-run rebuilt pipeline on unseen holdout FASTQ reads and verify output semantics."""
    holdout_fastq = "/tests/holdout/holdout_reads.fastq"
    holdout_buf = "/tmp/holdout_align.buf"
    holdout_out = "/work/out/holdout_output.json"

    assert os.path.exists(holdout_fastq), f"Holdout dataset missing at {holdout_fastq}."

    # Build and run Java gateway on holdout data
    build_cmd = "cd /app/rust_aligner && cargo build --release && cd /app/java_gateway && javac -d bin src/main/java/com/terminus/genomics/*.java"
    subprocess.run(build_cmd, shell=True, check=True)

    run_java = f"rm -f {holdout_buf} && java -Djava.library.path=/app/rust_aligner/target/release -cp /app/java_gateway/bin com.terminus.genomics.SequenceStreamService {holdout_fastq} false"
    subprocess.run(run_java, shell=True, check=True)

    run_py = f"python3 /app/python_annotator/annotator.py {holdout_buf} {holdout_out}"
    subprocess.run(run_py, shell=True, check=True)

    assert os.path.exists(holdout_out), f"Holdout output not produced at {holdout_out}."

    with open(holdout_out, "r") as f:
        holdout_data = json.load(f)

    assert holdout_data["total_reads_processed"] == 4, f"Expected 4 holdout reads, got {holdout_data['total_reads_processed']}."
    assert holdout_data["mean_phred_score"] >= 35.0, f"Holdout Phred score {holdout_data['mean_phred_score']} invalid."
