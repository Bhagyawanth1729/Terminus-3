pub mod decoder;
pub mod dictionary;

use decoder::DeltaDecoder;
use dictionary::DictionaryDecoder;
use std::os::raw::c_char;
use std::slice;

#[no_mangle]
pub unsafe extern "C" fn decode_delta_stream(
    compressed_ptr: *const u8,
    compressed_len: u64,
    out_timestamps_ptr: *mut i64,
    max_out: u64,
    out_neg_count: *mut u64,
) -> i32 {
    if compressed_ptr.is_null() || out_timestamps_ptr.is_null() || out_neg_count.is_null() {
        return -1;
    }

    let compressed = slice::from_raw_parts(compressed_ptr, compressed_len as usize);
    let out_buf = slice::from_raw_parts_mut(out_timestamps_ptr, max_out as usize);

    match DeltaDecoder::decode_stream(compressed, out_buf) {
        Ok((count, neg_count)) => {
            *out_neg_count = neg_count as u64;
            count as i32
        }
        Err(_) => -2,
    }
}

#[no_mangle]
pub unsafe extern "C" fn decode_dictionary_stream(
    dict_ptr: *const u8,
    dict_len: u64,
    out_json_buf: *mut c_char,
    max_json_len: u64,
) -> i32 {
    if dict_ptr.is_null() || out_json_buf.is_null() {
        return -1;
    }

    let dict_bytes = slice::from_raw_parts(dict_ptr, dict_len as usize);
    match DictionaryDecoder::decode_dictionary(dict_bytes) {
        Ok(strings) => {
            // Join string entries as comma-separated list
            let joined = strings.join(",");
            let c_str = std::ffi::CString::new(joined).unwrap_or_default();
            let bytes = c_str.as_bytes_with_nul();
            if bytes.len() > max_json_len as usize {
                return -3;
            }
            let out_slice = slice::from_raw_parts_mut(out_json_buf as *mut u8, bytes.len());
            out_slice.copy_from_slice(bytes);
            (bytes.len() - 1) as i32
        }
        Err(_) => -2,
    }
}
