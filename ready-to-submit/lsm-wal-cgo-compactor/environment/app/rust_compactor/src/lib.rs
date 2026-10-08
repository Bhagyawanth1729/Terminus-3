pub mod crc32c;
pub mod sstable;

use std::ffi::CStr;
use std::os::raw::c_char;
use std::slice;
use crate::sstable::compact_blocks;

#[no_mangle]
pub extern "C" fn cgo_compact_wal(
    path_ptr: *const c_char,
    data_ptr: *const u8,
    data_len: usize,
) -> u32 {
    if path_ptr.is_null() || data_ptr.is_null() || data_len == 0 {
        return 0;
    }

    let c_str = unsafe { CStr::from_ptr(path_ptr) };
    let path = match c_str.to_str() {
        Ok(s) => s,
        Err(_) => return 0,
    };

    let slice = unsafe { slice::from_raw_parts(data_ptr, data_len) };

    match compact_blocks(path, slice) {
        Ok(checksum) => checksum,
        Err(_) => 0,
    }
}
