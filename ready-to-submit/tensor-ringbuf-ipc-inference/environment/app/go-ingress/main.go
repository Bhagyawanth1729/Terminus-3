package main

/*
#cgo LDFLAGS: -L. -L/app/rust-engine/target/release -L/usr/local/lib -ltensor_engine
#include <stdint.h>
#include <stdlib.h>

void* tensor_engine_init(const char* shm_path);
int32_t tensor_engine_process_slot(void* engine, uint32_t slot_idx, float* out_logits, uint32_t max_logits);
void tensor_engine_free(void* engine);
*/
import "C"

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"sync"
	"sync/atomic"
	"time"
	"unsafe"
)

type IngressServer struct {
	mu        sync.Mutex
	rb        *SharedRingBuffer
	engine    unsafe.Pointer
	requestID uint64
}

type InferRequest struct {
	QueryID uint64  `json:"query_id"`
	Data    []int8  `json:"data"`
	Scale   float32 `json:"scale"`
}

type InferResponse struct {
	QueryID uint64    `json:"query_id"`
	Status  string    `json:"status"`
	Logits  []float32 `json:"logits,omitempty"`
	Error   string    `json:"error,omitempty"`
}

type MetricsResponse struct {
	TotalProcessed uint32 `json:"total_processed"`
	Head           uint32 `json:"head"`
	Tail           uint32 `json:"tail"`
}

func main() {
	rb, err := InitSharedMemory(ShmPath)
	if err != nil {
		log.Fatalf("Failed to init shared memory: %v", err)
	}
	defer rb.Close()

	cShmPath := C.CString(ShmPath)
	defer C.free(unsafe.Pointer(cShmPath))

	engine := C.tensor_engine_init(cShmPath)
	if engine == nil {
		log.Fatalf("Failed to initialize Rust tensor engine")
	}
	defer C.tensor_engine_free(engine)

	server := &IngressServer{
		rb:     rb,
		engine: engine,
	}

	http.HandleFunc("/infer", server.handleInfer)
	http.HandleFunc("/health", server.handleHealth)
	http.HandleFunc("/metrics", server.handleMetrics)

	port := "50052"
	if p := os.Getenv("PORT"); p != "" {
		port = p
	}

	log.Printf("Go Tensor Ingress Server listening on port %s...", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server exited with error: %v", err)
	}
}

func (s *IngressServer) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "OK"})
}

func (s *IngressServer) handleMetrics(w http.ResponseWriter, r *http.Request) {
	head := atomic.LoadUint32((*uint32)(unsafe.Pointer(&s.rb.data[0])))
	tail := atomic.LoadUint32((*uint32)(unsafe.Pointer(&s.rb.data[4])))
	total := atomic.LoadUint32((*uint32)(unsafe.Pointer(&s.rb.data[12])))

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(MetricsResponse{
		TotalProcessed: total,
		Head:           head,
		Tail:           tail,
	})
}

func (s *IngressServer) handleInfer(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req InferRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(InferResponse{
			Status: "ERROR",
			Error:  fmt.Sprintf("invalid json body: %v", err),
		})
		return
	}

	if len(req.Data) == 0 {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(InferResponse{
			Status: "ERROR",
			Error:  "tensor data cannot be empty",
		})
		return
	}

	if req.Scale == 0 {
		req.Scale = 1.0
	}

	reqID := atomic.AddUint64(&s.requestID, 1)
	if req.QueryID == 0 {
		req.QueryID = reqID
	}

	slotIdx, err := s.rb.WriteTensor(uint32(req.QueryID), req.Data, req.Scale)
	if err != nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(InferResponse{
			QueryID: req.QueryID,
			Status:  "ERROR",
			Error:   fmt.Sprintf("ringbuffer write error: %v", err),
		})
		return
	}

	// Process slot in Rust engine
	var logits [8]C.float
	res := C.tensor_engine_process_slot(s.engine, C.uint32_t(slotIdx), &logits[0], 8)
	if res != 0 {
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(InferResponse{
			QueryID: req.QueryID,
			Status:  "ERROR",
			Error:   fmt.Sprintf("rust engine execution failed with code: %d", res),
		})
		return
	}

	// Update slot state to completed
	slot := s.rb.getSlotHeaderPtr(slotIdx)
	atomic.StoreUint32(&slot.State, SlotStateCompleted)

	// Advance tail
	tailPtr := (*uint32)(unsafe.Pointer(&s.rb.data[4]))
	atomic.StoreUint32(tailPtr, slotIdx)

	outLogits := make([]float32, 8)
	for i := 0; i < 8; i++ {
		outLogits[i] = float32(logits[i])
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(InferResponse{
		QueryID: req.QueryID,
		Status:  "SUCCESS",
		Logits:  outLogits,
	})
}
