use std::fs::OpenOptions;
use std::io::Write;
use std::sync::atomic::{AtomicU32, Ordering};
use std::ffi::CStr;
use libc::c_char;

#[repr(C)]
pub struct RingItemC {
    pub query_id: u32,
    pub node_id: u64,
    pub distance: f32,
    pub vector_dim: u32,
    pub vector_data: [f32; 16],
}

pub struct RingBufferHeader {
    pub magic: u32,       // 0x484E5357 ("HNSW")
    pub capacity: u32,
    pub item_size: u32,
    pub write_head: AtomicU32,
    pub read_head: AtomicU32,
}

pub struct RingBuffer {
    pub file_path: String,
    pub capacity: usize,
    pub mmap_ptr: *mut u8,
    pub file_len: usize,
}

impl RingBuffer {
    pub fn new(path: &str, capacity: usize) -> Result<Self, String> {
        let item_size = 128usize;
        let header_size = 32usize;
        let total_size = header_size + capacity * item_size;

        let mut file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(path)
            .map_err(|e| format!("Failed to open ringbuf file: {}", e))?;

        file.set_len(total_size as u64)
            .map_err(|e| format!("Failed to set ringbuf file len: {}", e))?;

        let fd = std::os::unix::io::AsRawFd::as_raw_fd(&file);
        let mmap_ptr = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                total_size,
                libc::PROT_READ | libc::PROT_WRITE,
                libc::MAP_SHARED,
                fd,
                0,
            )
        };

        if mmap_ptr == libc::MAP_FAILED {
            return Err("mmap failed".to_string());
        }

        let rb = RingBuffer {
            file_path: path.to_string(),
            capacity,
            mmap_ptr: mmap_ptr as *mut u8,
            file_len: total_size,
        };

        unsafe {
            let magic_ptr = rb.mmap_ptr as *mut u32;
            let cap_ptr = rb.mmap_ptr.add(4) as *mut u32;
            let item_sz_ptr = rb.mmap_ptr.add(8) as *mut u32;
            
            std::ptr::write_volatile(magic_ptr, 0x484E5357);
            std::ptr::write_volatile(cap_ptr, capacity as u32);
            std::ptr::write_volatile(item_sz_ptr, item_size as u32);
        }

        Ok(rb)
    }

    pub fn write_item(&self, item: &RingItemC) -> bool {
        let header_size = 32usize;
        let item_size = 128usize;

        unsafe {
            let write_head_ptr = self.mmap_ptr.add(12) as *const AtomicU32;
            let current_head = (*write_head_ptr).load(Ordering::Relaxed);
            let slot_idx = (current_head as usize) % self.capacity;

            let slot_offset = header_size + slot_idx * item_size;
            let slot_ptr = self.mmap_ptr.add(slot_offset);

            // Copy payload bytes into shared memory slot
            let item_bytes = item as *const RingItemC as *const u8;
            std::ptr::copy_nonoverlapping(item_bytes, slot_ptr, std::mem::size_of::<RingItemC>());

            // BUG (Defect 2):
            // Using Ordering::Relaxed here permits CPU store reordering.
            // Payload memory stores above may not be visible to the reading process
            // before write_head is updated, resulting in torn reads under high QPS.
            // FIX: Change Ordering::Relaxed to Ordering::Release below!
            let next_head = current_head.wrapping_add(1);
            let write_head_atomic = &*(self.mmap_ptr.add(12) as *const AtomicU32);
            write_head_atomic.store(next_head, Ordering::Relaxed); // <--- BUG!
        }
        true
    }
}

impl Drop for RingBuffer {
    fn drop(&mut self) {
        if !self.mmap_ptr.is_null() && self.mmap_ptr != libc::MAP_FAILED as *mut u8 {
            unsafe {
                libc::munmap(self.mmap_ptr as *mut libc::c_void, self.file_len);
            }
        }
    }
}

#[no_mangle]
pub extern "C" fn hnsw_ringbuf_init(path: *const c_char, capacity: u32) -> *mut RingBuffer {
    if path.is_null() { return std::ptr::null_mut(); }
    let c_str = unsafe { CStr::from_ptr(path) };
    let path_str = match c_str.to_str() {
        Ok(s) => s,
        Err(_) => return std::ptr::null_mut(),
    };

    match RingBuffer::new(path_str, capacity as usize) {
        Ok(rb) => Box::into_raw(Box::new(rb)),
        Err(_) => std::ptr::null_mut(),
    }
}

#[no_mangle]
pub extern "C" fn hnsw_ringbuf_write(rb: *mut RingBuffer, item: *const RingItemC) -> i32 {
    if rb.is_null() || item.is_null() { return 0; }
    let rb_ref = unsafe { &*rb };
    let item_ref = unsafe { &*item };
    if rb_ref.write_item(item_ref) { 1 } else { 0 }
}

#[no_mangle]
pub extern "C" fn hnsw_ringbuf_free(rb: *mut RingBuffer) {
    if !rb.is_null() {
        unsafe { let _ = Box::from_raw(rb); }
    }
}
