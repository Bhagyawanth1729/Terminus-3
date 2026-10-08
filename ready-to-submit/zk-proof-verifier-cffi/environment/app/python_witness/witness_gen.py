import hashlib
import json
import sys

def generate_credential(user_id: str, secret_val: str) -> dict:
    """
    Generates a credential assertion payload containing public_scalar and proof_hex.
    """
    # BROKEN: Missing "LEAF:" domain separator prefix in leaf hash serialization!
    leaf_hash = hashlib.sha256(secret_val.encode('utf-8')).digest()

    pub_scalar_be = leaf_hash
    pub_scalar_le = pub_scalar_be[::-1]

    proof_digest = bytearray(32)
    prefix = b"ZK_PROOF_BN254_V1:" + pub_scalar_le
    for i, b in enumerate(prefix):
        proof_digest[i % 32] = (proof_digest[i % 32] + b * 31) & 0xFF

    return {
        "id": user_id,
        "public_scalar": pub_scalar_be.hex(),
        "proof_hex": bytes(proof_digest).hex()
    }

def main():
    users = [
        ("user_101", "secret_pass_101"),
        ("user_102", "secret_pass_102"),
        ("user_103", "secret_pass_103")
    ]

    creds = [generate_credential(uid, s) for uid, s in users]

    out_path = "/app/data/credentials.json"
    if len(sys.argv) > 1:
        out_path = sys.argv[1]

    with open(out_path, "w") as f:
        json.dump(creds, f, indent=2)
    print(f"Generated {len(creds)} credential payloads at {out_path}")

if __name__ == "__main__":
    main()
