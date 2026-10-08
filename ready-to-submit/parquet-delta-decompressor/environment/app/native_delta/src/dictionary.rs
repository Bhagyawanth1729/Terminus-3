pub struct DictionaryDecoder;

impl DictionaryDecoder {
    /// Decodes a dictionary page binary buffer into indexed string strings.
    /// Returns vector of decoded strings.
    pub fn decode_dictionary(dict_bytes: &[u8]) -> Result<Vec<String>, &'static str> {
        if dict_bytes.len() < 4 {
            return Err("Dictionary bytes too short");
        }

        // BROKEN: Assumes a fixed 4-byte little-endian u32 header for entry count!
        // Standard LEB128 varint encoding is required. When entry count >= 128, varint header
        // length is variable (2+ bytes), causing wrong entry count and corrupting data_offset!
        let entry_count = u32::from_le_bytes(dict_bytes[0..4].try_into().unwrap()) as usize;
        let mut offset = 4;

        let mut strings = Vec::with_capacity(entry_count);
        for _ in 0..entry_count {
            if offset >= dict_bytes.len() {
                break;
            }
            let str_len = dict_bytes[offset] as usize;
            offset += 1;
            if offset + str_len > dict_bytes.len() {
                break;
            }
            let s = String::from_utf8_lossy(&dict_bytes[offset..offset + str_len]).to_string();
            offset += str_len;
            strings.push(s);
        }

        Ok(strings)
    }
}
