The genomic sequence processing and variant discovery pipeline located in `/app` is producing invalid variant calls and failing under concurrent sequence batch streaming. The system consists of a Java sequence streaming gateway (`/app/java_gateway`), a Rust C-FFI k-mer dynamic programming alignment engine (`/app/rust_aligner`), and a Python IPC variant annotation daemon (`/app/python_annotator`).

Diagnose and repair all defects across the pipeline so that sequence alignment, memory synchronization, stream context handling, and Phred quality score calculations function correctly. Once repaired, execute `/app/build_and_run.sh` to compile the components and process the input FASTQ reads in `/app/data/sample_reads.fastq`. The pipeline must generate a valid VCF variant summary JSON report at `/app/output.json` with the following structure:

```json
{
  "total_reads_processed": 1000,
  "aligned_reads": 985,
  "unaligned_reads": 15,
  "mean_phred_score": 35.42,
  "variants": [
    {
      "chrom": "chr1",
      "pos": 10542,
      "ref": "A",
      "alt": "G",
      "quality_score": 38.5,
      "filter": "PASS",
      "allele_frequency": 0.485
    }
  ]
}
```

The pipeline must operate deterministically, maintain memory stability across high-frequency stream cancellations, and guarantee lock-free shared memory IPC consistency without torn reads under multi-threaded loads.
