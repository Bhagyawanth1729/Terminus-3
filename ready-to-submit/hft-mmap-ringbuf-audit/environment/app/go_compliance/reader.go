package main

/*
#cgo LDFLAGS: -L/app/rust_engine/target/release -L/app/lib -lrust_ringbuf -ldl -lpthread
#include "/app/rust_engine/include/ringbuf.h"
#include <stdlib.h>
*/
import "C"
import (
	"fmt"
	"unsafe"
)

type Trade struct {
	OrderID     uint64
	PriceScaled int64
	Quantity    uint64
	TimestampNS uint64
}

type RingReader struct {
	handle C.uintptr_t
}

func NewRingReader(shmPath string) (*RingReader, error) {
	cPath := C.CString(shmPath)
	defer C.free(unsafe.Pointer(cPath))

	handle := C.create_reader_handle(cPath)
	if handle == 0 {
		return nil, fmt.Errorf("failed to create ring reader handle for %s", shmPath)
	}

	return &RingReader{handle: handle}, nil
}

func (r *RingReader) ReadNext() (*Trade, bool) {
	var cRec C.TradeRecord
	res := C.read_next_trade(r.handle, &cRec)
	if res <= 0 {
		return nil, false
	}

	return &Trade{
		OrderID:     uint64(cRec.order_id),
		PriceScaled: int64(cRec.price_scaled),
		Quantity:    uint64(cRec.quantity),
		TimestampNS: uint64(cRec.timestamp_ns),
	}, true
}

func (r *RingReader) Free() {
	if r.handle != 0 {
		C.free_reader_handle(r.handle)
		r.handle = 0
	}
}

func GetActiveReaderCount() uint64 {
	return uint64(C.get_active_reader_count())
}
