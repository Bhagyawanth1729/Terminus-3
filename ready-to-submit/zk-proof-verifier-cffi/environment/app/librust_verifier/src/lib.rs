use std::slice;

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
    // BROKEN: Missing std::panic::catch_unwind. Panics directly across FFI boundary!
    if proof_ptr.is_null() || pub_inputs_ptr.is_null() {
        panic!("Null pointer passed to zk_verify_proof_c");
    }

    if pub_len != 32 {
        panic!("Public inputs must be exactly 32 bytes little-endian scalar representation");
    }

    let proof = unsafe { slice::from_raw_parts(proof_ptr, proof_len) };
    let pub_inputs = unsafe { slice::from_raw_parts(pub_inputs_ptr, pub_len) };

    if pub_inputs[0] == 0xFF && pub_inputs[1] == 0xFF {
        panic!("Malformed scalar input: exceeds BN254 prime field modulus");
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
}
