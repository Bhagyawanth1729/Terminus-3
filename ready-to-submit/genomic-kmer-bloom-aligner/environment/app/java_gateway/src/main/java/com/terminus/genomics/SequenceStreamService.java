package com.terminus.genomics;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;

public class SequenceStreamService {
    private final AtomicBoolean isCancelled = new AtomicBoolean(false);

    public void cancelStream() {
        isCancelled.set(true);
    }

    public int processFastqStream(String fastqPath, boolean simulateCancellation) {
        long alignerPtr = NativeAlignerBridge.alignerCreate();
        int processedCount = 0;

        try (BufferedReader reader = new BufferedReader(new FileReader(fastqPath))) {
            String header;
            long readId = 0;

            while ((header = reader.readLine()) != null) {
                String seq = reader.readLine();
                String strand = reader.readLine();
                String qual = reader.readLine();

                if (seq == null || strand == null || qual == null) {
                    break;
                }

                readId++;

                if (simulateCancellation && readId > 50) {
                    cancelStream();
                }

                if (isCancelled.get()) {
                    // BUG: On stream cancellation, the handler returns early without invoking
                    // NativeAlignerBridge.alignerDestroy(alignerPtr), leaking native C-heap context handles.
                    // FIX: Must invoke NativeAlignerBridge.alignerDestroy(alignerPtr) before returning or in a finally block.
                    System.err.println("gRPC Stream cancelled at read " + readId);
                    return processedCount;
                }

                int rc = NativeAlignerBridge.alignerProcessRead(alignerPtr, readId, seq, qual);
                if (rc == 0) {
                    processedCount++;
                }
            }
        } catch (IOException e) {
            e.printStackTrace();
        } finally {
            // Only destroys aligner on normal termination if not cancelled mid-stream
            if (!isCancelled.get()) {
                NativeAlignerBridge.alignerDestroy(alignerPtr);
            }
        }

        return processedCount;
    }

    public static void main(String[] args) {
        String fastqPath = args.length > 0 ? args[0] : "/app/data/sample_reads.fastq";
        boolean simulateCancel = args.length > 1 && Boolean.parseBoolean(args[1]);

        SequenceStreamService service = new SequenceStreamService();
        int count = service.processFastqStream(fastqPath, simulateCancel);
        System.out.println("Successfully processed " + count + " reads.");
    }
}
