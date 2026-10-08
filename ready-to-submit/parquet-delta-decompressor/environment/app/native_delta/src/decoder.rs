pub struct DeltaDecoder;

impl DeltaDecoder {
    /// Decodes a stream of packed delta values starting from initial_ts.
    /// Returns count of decoded timestamps written into out_buf, and count of negative deltas encountered.
    pub fn decode_stream(
        compressed: &[u8],
        out_buf: &mut [i64],
    ) -> Result<(usize, usize), &'static str> {
        if compressed.len() < 8 {
            return Err("Compressed buffer too short for header");
        }

        // Header: Initial timestamp (8 bytes, little endian)
        let initial_ts = i64::from_le_bytes(compressed[0..8].try_into().unwrap());
        if out_buf.is_empty() {
            return Ok((0, 0));
        }

        out_buf[0] = initial_ts;
        let mut curr_ts = initial_ts;
        let mut out_idx = 1;
        let mut neg_count = 0;

        let mut byte_idx = 8;
        while byte_idx < compressed.len() && out_idx < out_buf.len() {
            let bits_per_delta = compressed[byte_idx] as usize;
            byte_idx += 1;

            if bits_per_delta == 0 {
                continue;
            }

            let num_bytes_per_delta = (bits_per_delta + 7) / 8;
            if byte_idx + num_bytes_per_delta > compressed.len() {
                break;
            }

            // Extract raw bits (up to 8 bytes)
            let mut raw_bits: u64 = 0;
            for i in 0..num_bytes_per_delta {
                raw_bits |= (compressed[byte_idx + i] as u64) << (i * 8);
            }
            byte_idx += num_bytes_per_delta;

            // BROKEN: Zero-extends raw bits into i64 as a positive value!
            // Negative deltas (e.g. 0xFF in 8-bit = -1) are wrongly converted to +255!
            let signed_delta: i64 = raw_bits as i64;

            if signed_delta < 0 {
                neg_count += 1;
            }

            curr_ts = curr_ts.wrapping_add(signed_delta);
            out_buf[out_idx] = curr_ts;
            out_idx += 1;
        }

        Ok((out_idx, neg_count))
    }
}
