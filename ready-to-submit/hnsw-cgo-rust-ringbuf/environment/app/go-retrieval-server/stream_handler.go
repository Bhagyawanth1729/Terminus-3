package main

/*
#cgo LDFLAGS: -L${SRCDIR}/../librust_hnsw/target/release -lrust_hnsw -Wl,-rpath,${SRCDIR}/../librust_hnsw/target/release
#include "../librust_hnsw/include/hnsw_cffi.h"
*/
import "C"
import (
	"context"
	"fmt"
)

type SearchStreamHandler struct {
	bridge *HnswBridge
}

func NewSearchStreamHandler(bridge *HnswBridge) *SearchStreamHandler {
	return &SearchStreamHandler{bridge: bridge}
}

func (h *SearchStreamHandler) ProcessQueryBatch(ctx context.Context, queries [][]float32, k int) ([][]HnswResult, error) {
	// Create C-FFI search context
	searchCtx := C.hnsw_create_search_ctx(h.bridge.indexC)
	if searchCtx == nil {
		return nil, fmt.Errorf("failed to create rust search context")
	}

	// BUG (Defect 3):
	// Missing `defer C.hnsw_free_search_ctx(searchCtx)`!
	// If `ctx.Done()` triggers on client stream abort, this function returns early
	// without calling `C.hnsw_free_search_ctx(searchCtx)`, leaking native Rust search context handles!
	// FIX: Add `defer C.hnsw_free_search_ctx(searchCtx)` right here!

	allResults := make([][]HnswResult, 0, len(queries))
	for qIdx, query := range queries {
		select {
		case <-ctx.Done():
			// BUG: Early exit on cancellation leaks `searchCtx`!
			return nil, ctx.Err()
		default:
			res, err := h.bridge.SearchVector(uint32(qIdx), query, k)
			if err != nil {
				C.hnsw_free_search_ctx(searchCtx)
				return nil, err
			}
			allResults = append(allResults, res)
		}
	}

	// Only frees searchCtx on non-cancelled happy path
	C.hnsw_free_search_ctx(searchCtx)
	return allResults, nil
}
