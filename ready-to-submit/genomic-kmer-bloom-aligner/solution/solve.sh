#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Fixing Rust Ring Buffer Atomic Fence Ordering ==="
# Fix ringbuf.rs: replace Relaxed atomic store on write_head with Release store
sed -i 's/(*self.header).write_head.store(new_head, Ordering::Relaxed);/(*self.header).write_head.store(new_head, Ordering::Release);/g' /app/rust_aligner/src/ringbuf.rs

echo "=== Fixing Java gRPC Stream Cancellation Native Handle Cleanup ==="
# Fix SequenceStreamService.java: ensure alignerDestroy is called on stream cancellation
python3 -c '
path = "/app/java_gateway/src/main/java/com/terminus/genomics/SequenceStreamService.java"
with open(path, "r") as f:
    content = f.read()

# Replace early return on cancellation to call alignerDestroy
old_cancel_block = """                if (isCancelled.get()) {
                    // BUG: On stream cancellation, the handler returns early without invoking
                    // NativeAlignerBridge.alignerDestroy(alignerPtr), leaking native C-heap context handles.
                    // FIX: Must invoke NativeAlignerBridge.alignerDestroy(alignerPtr) before returning or in a finally block.
                    System.err.println("gRPC Stream cancelled at read " + readId);
                    return processedCount;
                }"""

new_cancel_block = """                if (isCancelled.get()) {
                    System.err.println("gRPC Stream cancelled at read " + readId);
                    NativeAlignerBridge.alignerDestroy(alignerPtr);
                    return processedCount;
                }"""

content = content.replace(old_cancel_block, new_cancel_block)

# Replace finally block to always call alignerDestroy
old_finally = """        } finally {
            // Only destroys aligner on normal termination if not cancelled mid-stream
            if (!isCancelled.get()) {
                NativeAlignerBridge.alignerDestroy(alignerPtr);
            }
        }"""

new_finally = """        } finally {
            NativeAlignerBridge.alignerDestroy(alignerPtr);
        }"""

content = content.replace(old_finally, new_finally)

with open(path, "w") as f:
    f.write(content)
'

echo "=== Fixing Python Phred Quality Score ASCII Offset ==="
# Fix annotator.py: replace ord(c) - 64 with Sanger format ord(c) - 33
sed -i 's/ord(c) - 64/ord(c) - 33/g' /app/python_annotator/annotator.py

echo "=== Rebuilding and Executing Pipeline ==="
/app/build_and_run.sh

echo "=== Oracle Solution Completed Successfully ==="
