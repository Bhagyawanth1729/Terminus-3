import os
import struct
import json
import sys

RINGBUF_PATH = "/tmp/genomic_align.buf"
OUTPUT_PATH = "/app/output.json"

def read_records_from_ringbuf(filepath):
    if not os.path.exists(filepath):
        print(f"Ring buffer file {filepath} not found.")
        return []

    records = []
    with open(filepath, "rb") as f:
        # Read header (32 bytes: magic u64, write_head u64, read_tail u64, item_count u64)
        header = f.read(32)
        if len(header) < 32:
            return []
        
        magic, write_head, read_tail, item_count = struct.unpack("<QQQQ", header)
        
        offset = 32
        data_bytes_to_read = write_head
        
        while offset < 32 + data_bytes_to_read:
            f.seek(offset)
            len_bytes = f.read(2)
            if len(len_bytes) < 2:
                break
            rec_len = struct.unpack("<H", len_bytes)[0]
            if rec_len == 0 or rec_len > 4096:
                break
            rec_data = f.read(rec_len)
            if len(rec_data) < rec_len:
                break
            
            rec_str = rec_data.decode("utf-8", errors="ignore")
            records.append(rec_str)
            offset += 2 + rec_len

    return records

def calculate_phred_score(qual_str):
    if not qual_str:
        return 0.0
    
    # BUG: Using Illumina Q+64 offset (ord(c) - 64) instead of Sanger Q+33 offset (ord(c) - 33)
    # FIX: Change 64 to 33: scores = [ord(c) - 33 for c in qual_str]
    scores = [ord(c) - 64 for c in qual_str]
    return sum(scores) / len(scores)

def process_and_annotate(ringbuf_path, output_path):
    raw_records = read_records_from_ringbuf(ringbuf_path)
    
    total_processed = len(raw_records)
    aligned_count = 0
    unaligned_count = 0
    phred_scores = []
    variants = []

    for rec in raw_records:
        parts = rec.split("|")
        if len(parts) < 7:
            unaligned_count += 1
            continue

        read_id_str, seq, qual, chrom, pos_str, ref, alt = parts[:7]
        read_id = int(read_id_str)
        pos = int(pos_str)

        score = calculate_phred_score(qual)
        phred_scores.append(score)
        aligned_count += 1

        if ref != alt:
            variants.append({
                "chrom": chrom,
                "pos": pos,
                "ref": ref,
                "alt": alt,
                "quality_score": round(score, 2),
                "filter": "PASS",
                "allele_frequency": 0.485
            })

    mean_phred = round(sum(phred_scores) / len(phred_scores), 2) if phred_scores else 0.0

    output_data = {
        "total_reads_processed": total_processed,
        "aligned_reads": aligned_count,
        "unaligned_reads": unaligned_count,
        "mean_phred_score": mean_phred,
        "variants": variants
    }

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"Wrote variant report to {output_path} with {total_processed} reads processed.")

if __name__ == "__main__":
    buf_file = sys.argv[1] if len(sys.argv) > 1 else RINGBUF_PATH
    out_file = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_PATH
    process_and_annotate(buf_file, out_file)
