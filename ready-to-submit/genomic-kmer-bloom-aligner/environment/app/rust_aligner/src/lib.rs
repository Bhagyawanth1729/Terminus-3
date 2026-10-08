pub mod ringbuf;

use ringbuf::SharedRingBuffer;
use std::ffi::CStr;
use std::os::raw::c_char;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

pub static ACTIVE_HANDLE_COUNT: AtomicU64 = AtomicU64::new(0);

pub struct AlignerContext {
    pub id: u64,
    pub matrix_buffer: Vec<u8>,
    pub ring_buffer: SharedRingBuffer,
}

#[no_mangle]
pub extern "C" fn aligner_create() -> *mut AlignerContext {
    let ring_buffer = SharedRingBuffer::create_or_open("/tmp/genomic_align.buf");
    let ctx = Box::new(AlignerContext {
        id: ACTIVE_HANDLE_COUNT.fetch_add(1, Ordering::SeqCst) + 1,
        matrix_buffer: vec![0u8; 64 * 1024], // 64KB C-heap matrix allocation
        ring_buffer,
    });
    Box::into_raw(ctx)
}

#[no_mangle]
pub extern "C" fn aligner_process_read(
    ctx_ptr: *mut AlignerContext,
    read_id: u64,
    seq: *const c_char,
    qual: *const c_char,
) -> i32 {
    if ctx_ptr.is_null() || seq.is_null() || qual.is_null() {
        return -1;
    }

    let ctx = unsafe { &*ctx_ptr };
    let c_seq = unsafe { CStr::from_ptr(seq) };
    let c_qual = unsafe { CStr::from_ptr(qual) };

    let seq_str = match c_seq.to_str() {
        Ok(s) => s,
        Err(_) => return -2,
    };
    let qual_str = match c_qual.to_str() {
        Ok(s) => s,
        Err(_) => return -2,
    };

    // Format alignment record payload: "READ_ID|SEQ|QUAL|CHROM|POS|REF|ALT"
    // Simple deterministic alignment for sample data:
    let chrom = "chr1";
    let pos = 10542 + (read_id % 100) * 10;
    let ref_base = "A";
    let alt_base = if read_id % 7 == 0 { "G" } else { "A" };

    let record = format!(
        "{}|{}|{}|{}|{}|{}|{}",
        read_id, seq_str, qual_str, chrom, pos, ref_base, alt_base
    );

    if ctx.ring_buffer.write_record(record.as_bytes()) {
        0
    } else {
        -3
    }
}

#[no_mangle]
pub extern "C" fn aligner_destroy(ctx_ptr: *mut AlignerContext) {
    if !ctx_ptr.is_null() {
        unsafe {
            let _ = Box::from_raw(ctx_ptr);
        }
        ACTIVE_HANDLE_COUNT.fetch_sub(1, Ordering::SeqCst);
    }
}

#[no_mangle]
pub extern "C" fn aligner_get_active_handles() -> u64 {
    ACTIVE_HANDLE_COUNT.load(Ordering::SeqCst)
}
