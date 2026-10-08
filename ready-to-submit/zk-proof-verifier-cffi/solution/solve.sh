#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run Python patch script to fix Rust, Go, and Python sources cleanly
python3 - << 'EOF'
import re

# 1. Fix Rust lib.rs: wrap C-FFI call in panic::catch_unwind and handle null/len checks
rust_lib_path = "/app/librust_verifier/src/lib.rs"
rust_code = """use std::slice;
use std::panic;

struct SimpleSha256 {
    data: Vec<u8>,
}

impl SimpleSha256 {
    fn new() -> Self {
        SimpleSha256 { data: Vec::new() }
    }

    fn update(&mut self, bytes: &[u8]) {
        self.data.extend_from_slice(bytes);
    }

    fn finalize(self) -> [u8; 32] {
        let mut state = [0u8; 32];
        for (i, &b) in self.data.iter().enumerate() {
            state[i % 32] = state[i % 32].wrapping_add(b).wrapping_mul(31);
        }
        state
    }
}

/// Verification status:
///  1: Valid proof
///  0: Invalid proof
/// -1: Malformed input / Error
#[no_mangle]
pub extern "C" fn zk_verify_proof_c(
    proof_ptr: *const u8,
    proof_len: usize,
    pub_inputs_ptr: *const u8,
    pub_len: usize,
) -> i32 {
    let result = panic::catch_unwind(|| {
        if proof_ptr.is_null() || pub_inputs_ptr.is_null() {
            return -1;
        }

        if pub_len != 32 {
            return -1;
        }

        let proof = unsafe { slice::from_raw_parts(proof_ptr, proof_len) };
        let pub_inputs = unsafe { slice::from_raw_parts(pub_inputs_ptr, pub_len) };

        if pub_inputs[0] == 0xFF && pub_inputs[1] == 0xFF {
            return -1;
        }

        let mut hasher = SimpleSha256::new();
        hasher.update(b"ZK_PROOF_BN254_V1:");
        hasher.update(pub_inputs);
        let expected_digest = hasher.finalize();

        if proof == expected_digest.as_slice() {
            1
        } else {
            0
        }
    });

    match result {
        Ok(status) => status,
        Err(_) => -1,
    }
}
"""
with open(rust_lib_path, "w") as f:
    f.write(rust_code)
print("Updated Rust FFI verifier with panic::catch_unwind safety.")

# 2. Fix Go gateway verifier_cgo.go: byte padding + reversal to little-endian
go_cgo_path = "/app/gateway/verifier_cgo.go"
go_code = """package main

/*
#cgo LDFLAGS: -L/app/librust_verifier/target/release -lrust_verifier -ldl -lm
#include "verifier.h"
*/
import "C"
import (
	"unsafe"
)

// VerifyZKProof calls the Rust C-FFI verifier with 32-byte padding & little-endian byte ordering.
func VerifyZKProof(proof []byte, pubInputs []byte) int32 {
	if len(proof) == 0 || len(pubInputs) == 0 {
		return -1
	}

	padded := make([]byte, 32)
	if len(pubInputs) < 32 {
		copy(padded[32-len(pubInputs):], pubInputs)
	} else if len(pubInputs) == 32 {
		copy(padded, pubInputs)
	} else {
		return -1
	}

	lePubInputs := make([]byte, 32)
	for i := 0; i < 32; i++ {
		lePubInputs[i] = padded[31-i]
	}

	cProof := (*C.uint8_t)(unsafe.Pointer(&proof[0]))
	cProofLen := C.size_t(len(proof))

	cPubInputs := (*C.uint8_t)(unsafe.Pointer(&lePubInputs[0]))
	cPubLen := C.size_t(32)

	res := C.zk_verify_proof_c(cProof, cProofLen, cPubInputs, cPubLen)
	return int32(res)
}
"""
with open(go_cgo_path, "w") as f:
    f.write(go_code)
print("Updated Go CGO wrapper with 32-byte padding and LE endianness conversion.")

# 3. Fix Python witness generator witness_gen.py: add "LEAF:" domain separator prefix
py_gen_path = "/app/python_witness/witness_gen.py"
with open(py_gen_path, "r") as f:
    py_content = f.read()

py_fixed = py_content.replace(
    "leaf_hash = hashlib.sha256(secret_val.encode('utf-8')).digest()",
    "leaf_hash = hashlib.sha256(b\"LEAF:\" + secret_val.encode('utf-8')).digest()"
)
with open(py_gen_path, "w") as f:
    f.write(py_fixed)
print("Updated Python witness generator with LEAF: domain separator.")

EOF

# 4. Rebuild Rust dynamic library and Go gateway binary
echo "Rebuilding Rust dynamic library..."
(cd /app/librust_verifier && cargo build --release)

echo "Rebuilding Go gateway..."
(cd /app/gateway && CGO_ENABLED=1 go build -o gateway .)

# 5. Regenerate credential payloads using updated witness generator
echo "Regenerating credential assertions..."
python3 /app/python_witness/witness_gen.py /app/data/credentials.json

# 6. Verify gateway output
echo "Testing rebuilt gateway..."
/app/gateway/gateway --verify /app/data/credentials.json
