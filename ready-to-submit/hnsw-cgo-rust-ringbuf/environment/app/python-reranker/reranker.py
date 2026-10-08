import json
import os
import sys
import numpy as np
from ringbuf_reader import RingBufferReader

def main():
    ring_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/hnsw_ring.buf"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "/app/output.json"

    print(f"Reading ring buffer from {ring_path}...")
    reader = RingBufferReader(file_path=ring_path)
    reader.open()

    items = reader.read_items()
    reader.close()

    print(f"Read {len(items)} items from ring buffer.")

    # Group candidate items by query_id
    query_groups = {}
    for item in items:
        qid = item["query_id"]
        if qid not in query_groups:
            query_groups[qid] = []
        query_groups[qid].append(item)

    queries_output = []
    for qid in sorted(query_groups.keys()):
        group = query_groups[qid]
        
        # Deduplicate candidates by node_id, preserving max distance score
        seen = {}
        for item in group:
            nid = item["node_id"]
            dist = item["distance"]
            if nid not in seen or dist > seen[nid]["distance"]:
                seen[nid] = item

        unique_items = list(seen.values())
        # Sort descending by distance score
        unique_items.sort(key=lambda x: x["distance"], reverse=True)

        top_k = []
        for rank, cand in enumerate(unique_items, start=1):
            top_k.append({
                "node_id": cand["node_id"],
                "score": round(float(cand["distance"]), 4),
                "reranked_rank": rank
            })

        queries_output.append({
            "query_id": qid,
            "top_k": top_k
        })

    result_payload = {
        "total_queries": len(queries_output),
        "queries": queries_output
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result_payload, f, indent=2)

    print(f"Successfully wrote re-ranked results for {len(queries_output)} queries to {output_path}")

if __name__ == "__main__":
    main()
