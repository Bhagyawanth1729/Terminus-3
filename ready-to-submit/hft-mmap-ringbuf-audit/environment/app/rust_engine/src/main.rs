use rust_ringbuf::{push_trade_record, init_ring_buffer};
use std::env;
use std::fs::File;
use std::io::Read;
use std::ffi::CString;

fn main() {
    let args: Vec<String> = env::args().collect();
    let tick_file = if args.len() > 1 { &args[1] } else { "/app/data/ticks_sample.bin" };
    let shm_path = if args.len() > 2 { &args[2] } else { "/tmp/orderbook_ring.buf" };

    let c_path = CString::new(shm_path).unwrap();
    init_ring_buffer(c_path.as_ptr(), 1024);

    let mut file = match File::open(tick_file) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("Failed to open tick file {}: {}", tick_file, e);
            std::process::exit(1);
        }
    };

    let mut buffer = Vec::new();
    file.read_to_end(&mut buffer).unwrap();

    let record_size = 32;
    let count = buffer.len() / record_size;
    println!("Publishing {} trade records to ring buffer...", count);

    for i in 0..count {
        let offset = i * record_size;
        let order_id = u64::from_le_bytes(buffer[offset..offset+8].try_into().unwrap());
        let price_scaled = i64::from_le_bytes(buffer[offset+8..offset+16].try_into().unwrap());
        let quantity = u64::from_le_bytes(buffer[offset+16..offset+24].try_into().unwrap());
        let timestamp_ns = u64::from_le_bytes(buffer[offset+24..offset+32].try_into().unwrap());

        push_trade_record(c_path.as_ptr(), order_id, price_scaled, quantity, timestamp_ns);
    }

    println!("Published {} trade records successfully.", count);
}
