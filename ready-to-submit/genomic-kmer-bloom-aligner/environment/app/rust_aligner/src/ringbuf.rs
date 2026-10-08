use std::sync::atomic::{AtomicU64, Ordering};
use std::fs::OpenOptions;
use libc::{c_void, mmap, MAP_SHARED, PROT_READ, PROT_WRITE};
use std::ptr;

pub const RINGBUF_HEADER_MAGIC: u64 = 0x47454E4F4D494353; // "GENOMICS"
pub const RINGBUF_CAPACITY: usize = 1024 * 1024; // 1MB buffer

#[repr(C)]
pub struct RingBufHeader {
    pub magic: u64,
    pub write_head: AtomicU64,
    pub read_tail: AtomicU64,
    pub item_count: AtomicU64,
}

pub struct SharedRingBuffer {
    ptr: *mut c_void,
    header: *mut RingBufHeader,
    buf: *mut u8,
}

impl SharedRingBuffer {
    pub fn create_or_open(filepath: &str) -> Self {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(filepath)
            .expect("Failed to open shared memory file");
        
        file.set_len((std::mem::size_of::<RingBufHeader>() + RINGBUF_CAPACITY) as u64)
            .expect("Failed to set file length");

        let fd = std::os::unix::io::AsRawFd::as_raw_fd(&file);
        let size = std::mem::size_of::<RingBufHeader>() + RINGBUF_CAPACITY;

        let mapped = unsafe {
            mmap(
                ptr::null_mut(),
                size,
                PROT_READ | PROT_WRITE,
                MAP_SHARED,
                fd,
                0,
            )
        };

        if mapped == libc::MAP_FAILED {
            panic!("mmap failed");
        }

        let header = mapped as *mut RingBufHeader;
        unsafe {
            if (*header).magic != RINGBUF_HEADER_MAGIC {
                (*header).magic = RINGBUF_HEADER_MAGIC;
                (*header).write_head.store(0, Ordering::SeqCst);
                (*header).read_tail.store(0, Ordering::SeqCst);
                (*header).item_count.store(0, Ordering::SeqCst);
            }
        }

        let buf = unsafe { (mapped as *mut u8).add(std::mem::size_of::<RingBufHeader>()) };

        SharedRingBuffer {
            ptr: mapped,
            header,
            buf,
        }
    }

    pub fn write_record(&self, record_data: &[u8]) -> bool {
        if record_data.len() > 4096 {
            return false;
        }

        unsafe {
            let current_head = (*self.header).write_head.load(Ordering::Relaxed);
            let offset = (current_head as usize) % RINGBUF_CAPACITY;

            // Write length prefix (2 bytes)
            let len = record_data.len() as u16;
            let len_bytes = len.to_le_bytes();

            let target_ptr = self.buf.add(offset);
            ptr::copy_nonoverlapping(len_bytes.as_ptr(), target_ptr, 2);
            ptr::copy_nonoverlapping(record_data.as_ptr(), target_ptr.add(2), record_data.len());

            let new_head = current_head + 2 + record_data.len() as u64;

            // BUG: Using Ordering::Relaxed permits CPU store reordering where the updated write_head
            // is visible to Python readers before the record bytes are fully flushed to shared memory.
            // FIX: Must change Ordering::Relaxed to Ordering::Release to enforce memory barrier.
            (*self.header).write_head.store(new_head, Ordering::Relaxed);
            (*self.header).item_count.fetch_add(1, Ordering::Relaxed);
        }
        true
    }
}
