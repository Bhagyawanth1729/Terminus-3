use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicBool, AtomicI32, Ordering};
use std::time::Duration;
use tokio::runtime::Runtime;

static ACTIVE_TOKIO_WORKERS: AtomicI32 = AtomicI32::new(0);

pub struct QueryEngine {
    runtime: Runtime,
    state: Mutex<EngineState>,
    cancel_flag: Arc<AtomicBool>,
}

struct EngineState {
    queries_run: u64,
    last_query_id: u64,
}

#[no_mangle]
pub extern "C" fn arrow_exec_init() -> *mut QueryEngine {
    let rt = match Runtime::new() {
        Ok(r) => r,
        Err(_) => return std::ptr::null_mut(),
    };
    let engine = Box::new(QueryEngine {
        runtime: rt,
        state: Mutex::new(EngineState {
            queries_run: 0,
            last_query_id: 0,
        }),
        cancel_flag: Arc::new(AtomicBool::new(false)),
    });
    Box::into_raw(engine)
}

#[no_mangle]
pub extern "C" fn arrow_exec_cancel(engine: *mut QueryEngine) -> i32 {
    if engine.is_null() {
        return -1;
    }
    let eng = unsafe { &*engine };
    eng.cancel_flag.store(true, Ordering::SeqCst);
    0
}

#[no_mangle]
pub extern "C" fn arrow_exec_get_active_threads() -> i32 {
    ACTIVE_TOKIO_WORKERS.load(Ordering::SeqCst)
}

#[no_mangle]
pub extern "C" fn arrow_exec_query(
    engine: *mut QueryEngine,
    query_id: u64,
    batch_count: i32,
    out_high: *mut i64,
    out_low: *mut u64,
) -> i32 {
    if engine.is_null() || out_high.is_null() || out_low.is_null() {
        return -1;
    }

    let eng = unsafe { &*engine };
    
    // Buggy lock acquisition: fails if lock is poisoned from a cancelled/panicked previous thread
    let mut state = match eng.state.lock() {
        Ok(s) => s,
        Err(_poisoned) => {
            eprintln!("Rust Engine Error: Mutex lock poisoned!");
            return -2;
        }
    };

    state.queries_run += 1;
    state.last_query_id = query_id;
    eng.cancel_flag.store(false, Ordering::SeqCst);

    let cancel_flag = eng.cancel_flag.clone();
    
    ACTIVE_TOKIO_WORKERS.fetch_add(1, Ordering::SeqCst);
    
    let handle = eng.runtime.spawn(async move {
        let mut sum_high: i64 = 0;
        let mut sum_low: u64 = 0;

        for _i in 0..batch_count {
            // BUG: cancel_flag is NOT polled during batch iteration in the buggy engine!
            // When cancelled, this worker task keeps running in background, leaking active threads.
            
            tokio::time::sleep(Duration::from_millis(50)).await;

            let add_low: u64 = 1_000_000_000_000_000_000;
            let (new_low, overflow) = sum_low.overflowing_add(add_low);
            sum_low = new_low;
            if overflow {
                sum_high += 1;
            }
            sum_high += 10;
        }
        ACTIVE_TOKIO_WORKERS.fetch_sub(1, Ordering::SeqCst);
        Ok((sum_high, sum_low))
    });

    match eng.runtime.block_on(handle) {
        Ok(Ok((h, l))) => {
            unsafe {
                *out_high = h;
                *out_low = l;
            }
            0
        }
        Ok(Err(_)) => -3,
        Err(_) => -4,
    }
}

#[no_mangle]
pub extern "C" fn arrow_exec_free(engine: *mut QueryEngine) {
    if !engine.is_null() {
        unsafe {
            let _ = Box::from_raw(engine);
        }
    }
}
