#!/bin/bash
set -e

echo "=== Applying Reference Oracle Solution for arrow-flight-cffi-recovery ==="

# 1. Update Rust libarrow_exec to handle cancellation and mutex lock poisoning recovery
cat << 'EOF' > /app/libarrow_exec/src/lib.rs
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
    
    // Mutex lock poisoning recovery
    let mut state = match eng.state.lock() {
        Ok(s) => s,
        Err(poisoned) => poisoned.into_inner(),
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
            // Check cancellation flag on each batch iteration
            if cancel_flag.load(Ordering::SeqCst) {
                ACTIVE_TOKIO_WORKERS.fetch_sub(1, Ordering::SeqCst);
                return Err("Cancelled");
            }

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
EOF

# 2. Update Go flight-server to trigger C-FFI cancellation and format Decimal128 exactly
cat << 'EOF' > /app/flight-server/main.go
package main

/*
#cgo LDFLAGS: -L. -L/app/flight-server -L/usr/local/lib -L/usr/lib -larrow_exec
#include <stdint.h>
#include <stdlib.h>

void* arrow_exec_init();
int32_t arrow_exec_query(void* engine, uint64_t query_id, int32_t batch_count, int64_t* out_high, uint64_t* out_low);
int32_t arrow_exec_cancel(void* engine);
int32_t arrow_exec_get_active_threads();
void arrow_exec_free(void* engine);
*/
import "C"

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"sync"
	"unsafe"
)

type Server struct {
	mu     sync.Mutex
	engine unsafe.Pointer
}

type QueryResponse struct {
	QueryID     uint64 `json:"query_id"`
	Status      string `json:"status"`
	DecimalHigh int64  `json:"decimal_high,omitempty"`
	DecimalLow  uint64 `json:"decimal_low,omitempty"`
	ExactString string `json:"exact_string,omitempty"`
	Error       string `json:"error,omitempty"`
}

type MetricsResponse struct {
	ActiveThreads int32 `json:"active_threads"`
}

func main() {
	engine := C.arrow_exec_init()
	if engine == nil {
		log.Fatalf("Failed to initialize Rust query engine")
	}

	server := &Server{engine: engine}

	http.HandleFunc("/query", server.handleQuery)
	http.HandleFunc("/cancel", server.handleCancel)
	http.HandleFunc("/metrics", server.handleMetrics)

	port := "50051"
	if p := os.Getenv("PORT"); p != "" {
		port = p
	}

	log.Printf("Go Arrow Flight server listening on port %s...", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server error: %v", err)
	}
}

func (s *Server) handleQuery(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	queryIDStr := r.URL.Query().Get("id")
	batchesStr := r.URL.Query().Get("batches")

	queryID, _ := strconv.ParseUint(queryIDStr, 10, 64)
	batches, _ := strconv.Atoi(batchesStr)
	if batches <= 0 {
		batches = 10
	}

	doneChan := make(chan struct{})
	var high C.int64_t
	var low C.uint64_t
	var res C.int32_t

	go func() {
		res = C.arrow_exec_query(s.engine, C.uint64_t(queryID), C.int32_t(batches), &high, &low)
		close(doneChan)
	}()

	select {
	case <-ctx.Done():
		log.Printf("Query %d cancelled by HTTP client context", queryID)
		C.arrow_exec_cancel(s.engine) // Trigger C-FFI cancellation!
		w.WriteHeader(http.StatusRequestTimeout)
		json.NewEncoder(w).Encode(QueryResponse{
			QueryID: queryID,
			Status:  "CANCELLED",
			Error:   "client context cancelled",
		})
		return
	case <-doneChan:
		if res != 0 {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(QueryResponse{
				QueryID: queryID,
				Status:  "ERROR",
				Error:   fmt.Sprintf("rust engine error code: %d", res),
			})
			return
		}

		exactStr := fmt.Sprintf("%d:%d", int64(high), uint64(low))
		resp := QueryResponse{
			QueryID:     queryID,
			Status:      "SUCCESS",
			DecimalHigh: int64(high),
			DecimalLow:  uint64(low),
			ExactString: exactStr,
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}
}

func (s *Server) handleCancel(w http.ResponseWriter, r *http.Request) {
	C.arrow_exec_cancel(s.engine)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "CANCEL_SIGNAL_SENT"})
}

func (s *Server) handleMetrics(w http.ResponseWriter, r *http.Request) {
	active := C.arrow_exec_get_active_threads()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(MetricsResponse{ActiveThreads: int32(active)})
}
EOF

# 3. Rebuild binary artifacts
/app/build_all.sh

echo "=== Reference Oracle Solution Applied Successfully ==="
