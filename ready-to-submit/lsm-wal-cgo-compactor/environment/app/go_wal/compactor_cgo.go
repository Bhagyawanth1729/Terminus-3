package main

/*
#cgo LDFLAGS: -L/app/lib -lrust_compactor -Wl,-rpath,/app/lib
#include <stdint.h>
#include <stdlib.h>

uint32_t cgo_compact_wal(const char* path_ptr, const uint8_t* data_ptr, uintptr_t data_len);
*/
import "C"
import (
	"fmt"
	"unsafe"
)

func CompactWALViaRust(outputPath string, rawData []byte) (uint32, error) {
	if len(rawData) == 0 {
		return 0, fmt.Errorf("empty raw data")
	}

	cPath := C.CString(outputPath)
	defer C.free(unsafe.Pointer(cPath))

	// Alignment Check & Bug in initial code:
	// BUG: passes raw slice pointer directly even if unaligned or slicing produces odd offset
	// FIX: ensure 8-byte aligned buffer allocation before C call if slice header isn't 8-byte aligned
	alignedBuf := rawData
	if uintptr(unsafe.Pointer(&rawData[0]))%8 != 0 {
		// In initial code, this alignment check was omitted, leading to unaligned slice pointer
		alignedBuf = make([]byte, len(rawData))
		copy(alignedBuf, rawData)
	}

	ptr := (*C.uint8_t)(unsafe.Pointer(&alignedBuf[0]))
	length := C.uintptr_t(len(alignedBuf))

	res := C.cgo_compact_wal(cPath, ptr, length)
	if res == 0 {
		return 0, fmt.Errorf("Rust compaction failed for %s", outputPath)
	}

	return uint32(res), nil
}
