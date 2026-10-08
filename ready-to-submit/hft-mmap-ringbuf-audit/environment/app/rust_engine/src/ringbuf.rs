use std::fs::OpenOptions;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::Mutex;
use libc::{c_void, mmap, munmap, MAP_SHARED, O_CREAT, O_RDWR, PROT_READ, PROT_WRITE};
use std::ffi::CStr;
use std::os::raw::c_char;

#[repr(C)]
#[derive(Debug, Clone, Copy, Default)]
pub struct TradeRecord {
    pub order_id: u64,
    pub price_scaled: i64,
    pub quantity: u64,
    pub timestamp_ns: u64,
}

#[repr(C)]
struct Header {
    magic: u32,
    capacity: u32,
    head: AtomicU64,
    tail: AtomicU64,
    reserved: [u8; 40],
}

const MAGIC: u32 = 0x48465431; // "HFT1"

static ACTIVE_READERS: AtomicUsize = AtomicUsize::new(0);

pub struct RingBuffer {
    ptr: *mut c_void,
    size: usize,
    capacity: usize,
}

impl RingBuffer {
    pub fn open_or_create(path: &str, capacity: usize) -> Result<Self, String> {
        let file_size = 64 + capacity * std::mem::size_of::<TradeRecord>();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(path)
            .map_err(|e| e.to_string())?;
        file.set_len(file_size as u64).map_err(|e| e.to_string())?;

        use std::os::unix::io::AsRawFd;
        let fd = file.as_raw_fd();

        let ptr = unsafe {
            mmap(
                std::ptr::null_mut(),
                file_size,
                PROT_READ | PROT_WRITE,
                MAP_SHARED,
                fd,
                0,
            )
        };

        if ptr == libc::MAP_FAILED {
            return Err("mmap failed".to_string());
        }

        let header = unsafe { &mut *(ptr as *mut Header) };
        if header.magic != MAGIC {
            header.magic = MAGIC;
            header.capacity = capacity as u32;
            header.head.store(0, Ordering::SeqCst);
            header.tail.store(0, Ordering::SeqCst);
        }

        Ok(RingBuffer {
            ptr,
            size: file_size,
            capacity,
        })
    }

    pub fn push(&self, record: TradeRecord) -> Result<(), String> {
        let header = unsafe { &*(self.ptr as *const Header) };
        let head = header.head.load(Ordering::Relaxed);
        let slots_ptr = unsafe { self.ptr.add(64) as *mut TradeRecord };

        let slot_idx = (head % (self.capacity as u64)) as usize;
        unsafe {
            let slot = slots_ptr.add(slot_idx);
            (*slot).order_id = record.order_id;
            (*slot).price_scaled = record.price_scaled;
            (*slot).quantity = record.quantity;
            (*slot).timestamp_ns = record.timestamp_ns;
        }

        // DEFECT: Relaxed ordering allows compiler/CPU to reorder slot writes after head advancement
        header.head.store(head + 1, Ordering::Relaxed);
        Ok(())
    }

    pub fn read_next(&self, tail_ref: &mut u64) -> Option<TradeRecord> {
        let header = unsafe { &*(self.ptr as *const Header) };
        let head = header.head.load(Ordering::Acquire);

        if *tail_ref >= head {
            return None;
        }

        let slots_ptr = unsafe { self.ptr.add(64) as *const TradeRecord };
        let slot_idx = (*tail_ref % (self.capacity as u64)) as usize;
        let record = unsafe { *slots_ptr.add(slot_idx) };

        *tail_ref += 1;
        Some(record)
    }
}

impl Drop for RingBuffer {
    fn drop(&mut self) {
        unsafe {
            munmap(self.ptr, self.size);
        }
    }
}

pub struct ReaderHandle {
    rb: RingBuffer,
    tail: u64,
}

#[no_mangle]
pub extern "C" fn init_ring_buffer(path: *const c_char, capacity: u32) -> i32 {
    if path.is_null() { return -1; }
    let c_str = unsafe { CStr::from_ptr(path) };
    let path_str = match c_str.to_str() {
        Ok(s) => s,
        Err(_) => return -1,
    };

    match RingBuffer::open_or_create(path_str, capacity as usize) {
        Ok(_) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub extern "C" fn push_trade_record(
    path: *const c_char,
    order_id: u64,
    price_scaled: i64,
    quantity: u64,
    timestamp_ns: u64,
) -> i32 {
    if path.is_null() { return -1; }
    let c_str = unsafe { CStr::from_ptr(path) };
    let path_str = match c_str.to_str() {
        Ok(s) => s,
        Err(_) => return -1,
    };

    let rb = match RingBuffer::open_or_create(path_str, 1024) {
        Ok(rb) => rb,
        Err(_) => return -1,
    };

    let rec = TradeRecord {
        order_id,
        price_scaled,
        quantity,
        timestamp_ns,
    };

    match rb.push(rec) {
        Ok(_) => 0,
        Err(_) => -1,
    }
}

#[no_mangle]
pub extern "C" fn create_reader_handle(path: *const c_char) -> usize {
    if path.is_null() { return 0; }
    let c_str = unsafe { CStr::from_ptr(path) };
    let path_str = match c_str.to_str() {
        Ok(s) => s,
        Err(_) => return 0,
    };

    let rb = match RingBuffer::open_or_create(path_str, 1024) {
        Ok(rb) => rb,
        Err(_) => return 0,
    };

    let handle = Box::new(ReaderHandle { rb, tail: 0 });
    ACTIVE_READERS.fetch_add(1, Ordering::SeqCst);
    Box::into_raw(handle) as usize
}

#[no_mangle]
pub extern "C" fn read_next_trade(handle_ptr: usize, out_record: *mut TradeRecord) -> i32 {
    if handle_ptr == 0 || out_record.is_null() { return -1; }
    let handle = unsafe { &mut *(handle_ptr as *mut ReaderHandle) };

    match handle.rb.read_next(&mut handle.tail) {
        Some(rec) => {
            unsafe { *out_record = rec; }
            1
        }
        None => 0,
    }
}

#[no_mangle]
pub extern "C" fn free_reader_handle(handle_ptr: usize) {
    if handle_ptr != 0 {
        let _ = unsafe { Box::from_raw(handle_ptr as *mut ReaderHandle) };
        ACTIVE_READERS.fetch_sub(1, Ordering::SeqCst);
    }
}

#[no_mangle]
pub extern "C" fn get_active_reader_count() -> u64 {
    ACTIVE_READERS.load(Ordering::SeqCst) as u64
}
