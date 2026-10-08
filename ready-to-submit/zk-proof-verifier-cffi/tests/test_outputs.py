import json
import os
import subprocess
import tempfile


def test_gateway_verification_success():
    """Verifies that the rebuilt Go gateway successfully verifies all credential payloads."""
    cmd = ["/app/gateway/gateway", "--verify", "/app/data/credentials.json"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, f"Gateway exited with non-zero code {res.returncode}. Output:\n{res.stdout}\nStderr:\n{res.stderr}"
    assert "Summary: 3 verified, 0 rejected, 0 errors out of 3 total" in res.stdout, f"Gateway output did not report 3 verified credentials:\n{res.stdout}"


def test_ffi_panic_safety():
    """Verifies that passing malformed or out-of-bounds scalar inputs returns status -1 cleanly without panicking/crashing."""
    malformed_payload = [
        {
            "id": "malformed_1",
            "public_scalar": "ffff000000000000000000000000000000000000000000000000000000000000",
            "proof_hex": "1122334455667788990011223344556677889900112233445566778899001122"
        }
    ]

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(malformed_payload, f)
        tmp_path = f.name

    try:
        cmd = ["/app/gateway/gateway", "--verify", tmp_path]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert res.returncode == 0, f"Gateway process crashed on malformed FFI input! Return code: {res.returncode}\nStderr: {res.stderr}"
        assert "ERROR (-1)" in res.stdout, f"Expected ERROR (-1) for malformed scalar input. Output:\n{res.stdout}"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_witness_generator_domain_separator():
    """Verifies python_witness generator produces domain-separated Merkle leaf hashes matching holdout expectations."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        tmp_path = f.name

    try:
        cmd = ["python3", "/app/python_witness/witness_gen.py", tmp_path]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert res.returncode == 0, f"witness_gen.py failed: {res.stderr}\n{res.stdout}"

        with open(tmp_path, "r") as f:
            generated = json.load(f)

        assert len(generated) == 3, f"Expected 3 credentials, got {len(generated)}"
        for cred in generated:
            assert "id" in cred
            assert "public_scalar" in cred
            assert "proof_hex" in cred
            assert len(cred["public_scalar"]) == 64
            assert len(cred["proof_hex"]) == 64

        holdout_path = "/tests/holdout/holdout_proofs.json"
        if os.path.exists(holdout_path):
            with open(holdout_path, "r") as f:
                holdout_data = json.load(f)
            cmd_verify = ["/app/gateway/gateway", "--verify", holdout_path]
            res_h = subprocess.run(cmd_verify, capture_output=True, text=True, timeout=30)
            assert res_h.returncode == 0, f"Gateway failed on holdout verification: {res_h.stderr}"
            assert f"Summary: {len(holdout_data)} verified, 0 rejected, 0 errors out of {len(holdout_data)} total" in res_h.stdout, f"Holdout proofs failed verification:\n{res_h.stdout}"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
