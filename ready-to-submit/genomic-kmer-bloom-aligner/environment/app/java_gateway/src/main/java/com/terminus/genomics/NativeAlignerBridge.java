package com.terminus.genomics;

public class NativeAlignerBridge {
    static {
        try {
            System.loadLibrary("rust_aligner");
        } catch (UnsatisfiedLinkError e) {
            System.load("/app/rust_aligner/target/release/librust_aligner.so");
        }
    }

    public static native long alignerCreate();
    public static native int alignerProcessRead(long ctxPtr, long readId, String seq, String qual);
    public static native void alignerDestroy(long ctxPtr);
    public static native long alignerGetActiveHandles();
}
