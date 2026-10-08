use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::fs::{File, OpenOptions};
use std::io::{Write, Read};
use crate::crc32c::crc32c;

pub static ATOMIC_WRITE_CURSOR: AtomicU64 = AtomicU64::new(0);

pub struct SSTableRegistry {
    pub active_file_count: u32,
}

pub static SSTABLE_REGISTRY: Mutex<SSTableRegistry> = Mutex::new(SSTableRegistry {
    active_file_count: 0,
});

pub fn compact_blocks(path: &str, raw_data: &[u8]) -> Result<u32, String> {
    // Lock poisoning bug: mutex lock without poisoning recovery in initial code
    let mut reg = match SSTABLE_REGISTRY.lock() {
        Ok(guard) => guard,
        Err(_poisoned) => {
            // BUG: fails to recover from poisoned lock in initial version
            return Err("SSTable registry lock poisoned".to_string());
            // FIX: return poisoned.into_inner();
        }
    };

    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(path)
        .map_err(|e| format!("Failed to open file: {}", e))?;

    let checksum = crc32c(raw_data);
    let header = format!("SST21\nLEN:{}\nCRC:{:08x}\n", raw_data.len(), checksum);

    file.write_all(header.as_bytes())
        .map_err(|e| format!("Header write failed: {}", e))?;
    file.write_all(raw_data)
        .map_err(|e| format!("Data write failed: {}", e))?;

    // Atomic ordering bug: Ordering::Relaxed in initial code
    // BUG: Ordering::Relaxed allows memory write reordering before flush
    ATOMIC_WRITE_CURSOR.store(raw_data.len() as u64, Ordering::Relaxed);
    // FIX: ATOMIC_WRITE_CURSOR.store(raw_data.len() as u64, Ordering::Release);

    reg.active_file_count += 1;
    Ok(checksum)
}
