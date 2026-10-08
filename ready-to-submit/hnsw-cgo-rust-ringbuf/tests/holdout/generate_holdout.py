import os
import struct
import numpy as np

def generate_holdout_dataset(output_dir="."):
    os.makedirs(output_dir, exist_ok=True)
    emb_path = os.path.join(output_dir, "holdout_embeddings.bin")
    query_path = os.path.join(output_dir, "holdout_queries.bin")

    num_elements = 200
    dim = 16
    np.random.seed(1337)

    # Base node IDs with high-bit values exceeding 2^31 - 1
    # e.g., 0x8000_0000_0000_1000 -> 9223372036854779904
    base_high_id = 0x8000_0000_0000_1000

    print(f"Generating holdout dataset at {output_dir}...")
    with open(emb_path, "wb") as f:
        f.write(struct.pack("<II", num_elements, dim))
        for i in range(num_elements):
            node_id = base_high_id + i + 1
            f.write(struct.pack("<Q", node_id))
            vec = np.random.randn(dim).astype(np.float32)
            vec /= np.linalg.norm(vec)
            f.write(vec.tobytes())

    num_queries = 20
    with open(query_path, "wb") as f:
        f.write(struct.pack("<II", num_queries, dim))
        for i in range(num_queries):
            qvec = np.random.randn(dim).astype(np.float32)
            qvec /= np.linalg.norm(qvec)
            f.write(qvec.tobytes())

    print("Holdout generation complete.")

if __name__ == "__main__":
    generate_holdout_dataset()
