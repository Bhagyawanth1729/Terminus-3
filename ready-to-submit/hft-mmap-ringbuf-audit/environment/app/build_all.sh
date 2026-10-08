#!/bin/bash
set -e

mkdir -p /app/lib

# 1. Build Rust library and binary
cd /app/rust_engine
cargo build --release
cp target/release/librust_ringbuf.so /app/lib/
cp target/release/rust_producer /app/

# 2. Build Go compliance binary
cd /app/go_compliance
CGO_ENABLED=1 CGO_LDFLAGS="-L/app/lib -Wl,-rpath,/app/lib -lrust_ringbuf -ldl -lpthread" go build -o /app/go_compliance_bin .

# 3. Build Java audit app
cd /app/java_audit
mkdir -p build/classes
javac -d build/classes src/main/java/com/terminus/audit/*.java
cd build/classes
jar cfe /app/java_audit.jar com.terminus.audit.Main com/terminus/audit/*.class

echo "All components built successfully."
