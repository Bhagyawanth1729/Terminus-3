import os
import struct
import numpy as np

def generate_binary_dataset(output_dir=None):
    if output_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, "dataset")

    os.makedirs(output_dir, exist_ok=True)
    emb_path = os.path.join(output_dir, "embeddings.bin")
    query_path = os.path.join(output_dir, "queries.bin")

    num_elements = 100
    dim = 16
    np.random.seed(42)

    # Base node IDs with high-bit values (> 2^31 - 1, up to 2^64 - 1)
    base_high_id = 0x8000_0000_0000_0000

    print(f"Generating {num_elements} embeddings (dim={dim}) to {emb_path}...")
    with open(emb_path, "wb") as f:
        f.write(struct.pack("<II", num_elements, dim))
        for i in range(num_elements):
            node_id = base_high_id + i + 1
            f.write(struct.pack("<Q", node_id))
            vec = np.random.randn(dim).astype(np.float32)
            vec /= np.linalg.norm(vec)
            f.write(vec.tobytes())

    num_queries = 10
    print(f"Generating {num_queries} queries (dim={dim}) to {query_path}...")
    with open(query_path, "wb") as f:
        f.write(struct.pack("<II", num_queries, dim))
        for i in range(num_queries):
            qvec = np.random.randn(dim).astype(np.float32)
            qvec /= np.linalg.norm(qvec)
            f.write(qvec.tobytes())

    print("Data generation complete.")

if __name__ == "__main__":
    generate_binary_dataset()
