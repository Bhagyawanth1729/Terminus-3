use std::ffi::CStr;
use std::fs::OpenOptions;
use std::os::raw::c_char;
use std::os::unix::fs::OpenOptionsExt;
use std::sync::atomic::{AtomicU32, Ordering};

pub const RINGBUF_CAPACITY: usize = 64;
pub const SIMD_ALIGNMENT: usize = 64;

pub const SLOT_STATE_EMPTY: u32 = 0;
pub const SLOT_STATE_WRITING: u32 = 1;
pub const SLOT_STATE_READY: u32 = 2;
pub const SLOT_STATE_PROCESSING: u32 = 3;
pub const SLOT_STATE_COMPLETED: u32 = 4;
pub const SLOT_STATE_CANCELLED: u32 = 5;

#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct SlotHeader {
    pub slot_id: u32,
    pub state: u32,
    pub num_elements: u32,
    pub scale_factor_bits: u32,
    pub data_offset: u32,
    pub pad: [u32; 3],
}

#[repr(C)]
pub struct RingBufferHeader {
    pub head: AtomicU32,
    pub tail: AtomicU32,
    pub capacity: u32,
    pub total_processed: AtomicU32,
    pub slots: [SlotHeader; RINGBUF_CAPACITY],
}

pub struct TensorEngine {
    pub base_ptr: *mut u8,
    pub size: usize,
}

// Fixed 8x8 weight projection matrix for logit calculation
static WEIGHT_MATRIX: [[f32; 8]; 8] = [
    [0.25, -0.50, 0.75, 0.10, -0.20, 0.30, 0.15, -0.05],
    [-0.10, 0.40, -0.30, 0.80, 0.05, -0.15, 0.25, 0.50],
    [0.60, 0.20, -0.10, -0.40, 0.90, -0.05, 0.10, -0.30],
    [-0.35, 0.15, 0.45, -0.25, 0.10, 0.70, -0.60, 0.20],
    [0.12, -0.24, 0.36, -0.48, 0.60, -0.72, 0.84, -0.96],
    [0.50, 0.50, -0.50, -0.50, 0.25, 0.25, -0.25, -0.25],
    [-0.70, 0.10, 0.30, 0.20, -0.40, 0.50, 0.60, -0.10],
    [0.30, -0.60, 0.10, 0.40, -0.50, 0.20, -0.30, 0.80],
];

#[no_mangle]
pub extern "C" fn tensor_engine_init(shm_path: *const c_char) -> *mut TensorEngine {
    let path = if shm_path.is_null() {
        "/dev/shm/tensor_ringbuf.shm"
    } else {
        unsafe {
            match CStr::from_ptr(shm_path).to_str() {
                Ok(s) => s,
                Err(_) => return std::ptr::null_mut(),
            }
        }
    };

    let file = match OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
    {
        Ok(f) => f,
        Err(_) => return std::ptr::null_mut(),
    };

    use std::os::unix::io::AsRawFd;
    let fd = file.as_raw_fd();
    let size = std::mem::size_of::<RingBufferHeader>() + (RINGBUF_CAPACITY * 4096) + 4096;

    let ptr = unsafe {
        libc::mmap(
            std::ptr::null_mut(),
            size,
            libc::PROT_READ | libc::PROT_WRITE,
            libc::MAP_SHARED,
            fd,
            0,
        )
    };

    if ptr == libc::MAP_FAILED {
        return std::ptr::null_mut();
    }

    let engine = Box::new(TensorEngine {
        base_ptr: ptr as *mut u8,
        size,
    });

    Box::into_raw(engine)
}

#[no_mangle]
pub extern "C" fn tensor_engine_process_slot(
    engine: *mut TensorEngine,
    slot_idx: u32,
    out_logits: *mut f32,
    max_logits: u32,
) -> i32 {
    if engine.is_null() || out_logits.is_null() || max_logits < 8 {
        return -1;
    }

    let eng = unsafe { &*engine };
    let header = unsafe { &mut *(eng.base_ptr as *mut RingBufferHeader) };

    if slot_idx as usize >= RINGBUF_CAPACITY {
        return -1;
    }

    let slot = &header.slots[slot_idx as usize];
    if slot.state != SLOT_STATE_READY {
        return -3; // Slot not in READY state
    }

    // Verify 64-byte hardware SIMD alignment
    let data_offset = slot.data_offset as usize;
    let payload_ptr = unsafe { eng.base_ptr.add(data_offset) };
    if (payload_ptr as usize) % SIMD_ALIGNMENT != 0 {
        // Unaligned memory access error
        return -2;
    }

    let num_elements = slot.num_elements as usize;
    if num_elements == 0 || num_elements > 4096 {
        return -4;
    }

    let raw_slice = unsafe { std::slice::from_raw_parts(payload_ptr as *const i8, num_elements) };
    let scale = f32::from_bits(slot.scale_factor_bits);

    // Compute 8 output logits using SIMD projection matrix
    let mut logits = [0.0f32; 8];
    for logit_idx in 0..8 {
        let mut sum = 0.0f32;
        let w_row = &WEIGHT_MATRIX[logit_idx];
        for i in 0..num_elements {
            let weight = w_row[i % 8];
            let val = (raw_slice[i] as f32) * scale;
            sum += val * weight;
        }
        logits[logit_idx] = sum;
    }

    unsafe {
        for i in 0..8 {
            *out_logits.add(i) = logits[i];
        }
    }

    header.total_processed.fetch_add(1, Ordering::SeqCst);
    0
}

#[no_mangle]
pub extern "C" fn tensor_engine_free(engine: *mut TensorEngine) {
    if !engine.is_null() {
        unsafe {
            let eng = Box::from_raw(engine);
            libc::munmap(eng.base_ptr as *mut libc::c_void, eng.size);
        }
    }
}
