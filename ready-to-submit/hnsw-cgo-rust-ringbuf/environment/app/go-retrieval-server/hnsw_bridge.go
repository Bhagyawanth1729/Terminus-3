package main

/*
#cgo LDFLAGS: -L${SRCDIR}/../librust_hnsw/target/release -lrust_hnsw -Wl,-rpath,${SRCDIR}/../librust_hnsw/target/release
#include "../librust_hnsw/include/hnsw_cffi.h"
*/
import "C"
import (
	"fmt"
	"unsafe"
)

type HnswResult struct {
	NodeID   uint64
	Distance float32
}

type HnswBridge struct {
	indexC C.HnswIndexPtr
	ringC  C.RingBufPtr
	dim    uint32
}

func NewHnswBridge(dim uint32, maxElements size_t, ringPath string, ringCap uint32) (*HnswBridge, error) {
	idx := C.hnsw_init_index(C.uint32_t(dim), C.size_t(maxElements))
	if idx == nil {
		return nil, fmt.Errorf("failed to init rust hnsw index")
	}

	cPath := C.CString(ringPath)
	defer C.free(unsafe.Pointer(cPath))

	ring := C.hnsw_ringbuf_init(cPath, C.uint32_t(ringCap))
	if ring == nil {
		return nil, fmt.Errorf("failed to init rust ringbuf at %s", ringPath)
	}

	return &HnswBridge{
		indexC: idx,
		ringC:  ring,
		dim:    dim,
	}, nil
}

func (b *HnswBridge) AddPoint(nodeID uint64, vec []float32) bool {
	if len(vec) != int(b.dim) {
		return false
	}
	res := C.hnsw_add_point(b.indexC, C.uint64_t(nodeID), (*C.float)(&vec[0]))
	return res == 1
}

func (b *HnswBridge) SearchVector(queryID uint32, query []float32, k int) ([]HnswResult, error) {
	if len(query) != int(b.dim) {
		return nil, fmt.Errorf("query dim mismatch")
	}

	cResults := make([]C.hnsw_result_c, k)
	n := C.hnsw_search(
		b.indexC,
		(*C.float)(&query[0]),
		C.size_t(k),
		(*C.hnsw_result_c)(&cResults[0]),
	)

	results := make([]HnswResult, 0, n)
	for i := 0; i < int(n); i++ {
		cRes := cResults[i]

		// BUG (Defect 1):
		// Casting uint64_t to int64 sign-extends 64-bit node IDs > 2^31 - 1
		// (e.g. 0x8000000000000000 -> -9223372036854775808).
		// The check below rejects negative node IDs, truncating high node ID traversal!
		// FIX: Change `int64(cRes.node_id)` to `uint64(cRes.node_id)` below!
		signedID := int64(cRes.node_id) // <--- BUG!
		if signedID < 0 {
			continue // <--- Rejects large node IDs!
		}
		nodeID := uint64(signedID)

		dist := float32(cRes.distance)
		results = append(results, HnswResult{
			NodeID:   nodeID,
			Distance: dist,
		})

		// Write to shared memory ring buffer for Python sidecar
		var ringItem C.ring_item_c
		ringItem.query_id = C.uint32_t(queryID)
		ringItem.node_id = C.uint64_t(nodeID)
		ringItem.distance = C.float(dist)
		ringItem.vector_dim = C.uint32_t(len(query))
		for j := 0; j < len(query) && j < 16; j++ {
			ringItem.vector_data[j] = C.float(query[j])
		}

		C.hnsw_ringbuf_write(b.ringC, &ringItem)
	}

	return results, nil
}

type size_t = C.size_t
