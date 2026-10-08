#!/bin/bash
set -euo pipefail

echo "==> Building Rust Aligner Shared Library..."
cd /app/rust_aligner
cargo build --release

echo "==> Compiling Java Sequence Gateway..."
cd /app/java_gateway
mkdir -p bin
javac -d bin src/main/java/com/terminus/genomics/*.java

echo "==> Running Java Sequence Gateway..."
rm -f /tmp/genomic_align.buf
java -Djava.library.path=/app/rust_aligner/target/release -cp bin com.terminus.genomics.SequenceStreamService /app/data/sample_reads.fastq false

echo "==> Running Python Variant Annotator..."
python3 /app/python_annotator/annotator.py /tmp/genomic_align.buf /app/output.json

echo "==> Pipeline Execution Complete."
