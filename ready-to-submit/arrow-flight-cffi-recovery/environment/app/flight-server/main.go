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
	"math"
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
	QueryID     uint64  `json:"query_id"`
	Status      string  `json:"status"`
	ResultFloat float64 `json:"result_float,omitempty"`
	DecimalHigh int64   `json:"decimal_high,omitempty"`
	DecimalLow  uint64  `json:"decimal_low,omitempty"`
	ExactString string  `json:"exact_string,omitempty"`
	Error       string  `json:"error,omitempty"`
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
		// BUG: Context cancellation does NOT invoke C.arrow_exec_cancel!
		// The Rust execution engine keeps running in background, leaking threads.
		log.Printf("Query %d cancelled by HTTP client context", queryID)
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

		// BUG: Decimal precision is degraded to float64 lossy value instead of exact string/fields
		lossyVal := float64(high)*math.Pow(2, 64) + float64(low)

		resp := QueryResponse{
			QueryID:     queryID,
			Status:      "SUCCESS",
			ResultFloat: lossyVal, // Bug: float lossy representation!
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
