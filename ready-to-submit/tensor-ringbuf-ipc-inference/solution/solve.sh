#!/bin/bash
set -euo pipefail

echo "=== Applying Reference Oracle Solution for tensor-ringbuf-ipc-inference ==="

# 1. Update Go ringbuf.go to enforce 64-byte SIMD cache alignment and LittleEndian scale factor bits
cat << 'EOF' > /app/go-ingress/ringbuf.go
package main

import (
	"encoding/binary"
	"fmt"
	"math"
	"os"
	"sync/atomic"
	"syscall"
	"unsafe"
)

const (
	ShmPath          = "/dev/shm/tensor_ringbuf.shm"
	RingCapacity     = 64
	SlotDataMaxSize  = 4096
	SimdAlignment    = 64

	SlotStateEmpty      uint32 = 0
	SlotStateWriting    uint32 = 1
	SlotStateReady      uint32 = 2
	SlotStateProcessing uint32 = 3
	SlotStateCompleted  uint32 = 4
	SlotStateCancelled  uint32 = 5
)

// SlotHeader layout matches C / Rust struct (32 bytes)
type SlotHeader struct {
	SlotID           uint32
	State            uint32
	NumElements      uint32
	ScaleFactorBits  uint32
	DataOffset       uint32
	Pad0             uint32
	Pad1             uint32
	Pad2             uint32
}

const (
	SlotHeaderSize = 32
	HeaderSize     = 16 + (RingCapacity * SlotHeaderSize)
)

type SharedRingBuffer struct {
	file *os.File
	data []byte
	size int
}

func InitSharedMemory(path string) (*SharedRingBuffer, error) {
	totalSize := HeaderSize + (RingCapacity * SlotDataMaxSize) + 4096

	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0666)
	if err != nil {
		return nil, fmt.Errorf("failed to open shm file: %w", err)
	}

	if err := f.Truncate(int64(totalSize)); err != nil {
		f.Close()
		return nil, fmt.Errorf("failed to truncate shm file: %w", err)
	}

	data, err := syscall.Mmap(int(f.Fd()), 0, totalSize, syscall.PROT_READ|syscall.PROT_WRITE, syscall.MAP_SHARED)
	if err != nil {
		f.Close()
		return nil, fmt.Errorf("failed to mmap shm: %w", err)
	}

	rb := &SharedRingBuffer{
		file: f,
		data: data,
		size: totalSize,
	}

	// Initialize header capacity if not set
	capPtr := (*uint32)(unsafe.Pointer(&data[8]))
	if *capPtr == 0 {
		*capPtr = RingCapacity
	}

	return rb, nil
}

func (rb *SharedRingBuffer) Close() error {
	if rb.data != nil {
		syscall.Munmap(rb.data)
	}
	if rb.file != nil {
		return rb.file.Close()
	}
	return nil
}

func (rb *SharedRingBuffer) getSlotHeaderPtr(slotIdx uint32) *SlotHeader {
	offset := 16 + (slotIdx * SlotHeaderSize)
	return (*SlotHeader)(unsafe.Pointer(&rb.data[offset]))
}

// Fixed WriteTensor:
// 1) Aligns raw payload offset to 64-byte boundary using (offset + 63) & ^63
// 2) Uses LittleEndian byte order for IEEE-754 float32 scale factor bits
func (rb *SharedRingBuffer) WriteTensor(slotID uint32, tensorData []int8, scaleFactor float32) (uint32, error) {
	headPtr := (*uint32)(unsafe.Pointer(&rb.data[0]))
	slotIdx := atomic.AddUint32(headPtr, 1) % RingCapacity

	slot := rb.getSlotHeaderPtr(slotIdx)

	atomic.StoreUint32(&slot.State, SlotStateWriting)
	slot.SlotID = slotID
	slot.NumElements = uint32(len(tensorData))

	// Fix 2: Use LittleEndian encoding for float32 bits
	scaleBits := math.Float32bits(scaleFactor)
	var scaleBuf [4]byte
	binary.LittleEndian.PutUint32(scaleBuf[:], scaleBits)
	slot.ScaleFactorBits = *(*uint32)(unsafe.Pointer(&scaleBuf[0]))

	// Fix 1: Calculate strictly 64-byte aligned data offset
	baseSlotOffset := HeaderSize + int(slotIdx)*SlotDataMaxSize
	alignedOffset := (baseSlotOffset + 63) &^ 63
	slot.DataOffset = uint32(alignedOffset)

	// Copy tensor data to aligned offset
	payloadSlice := rb.data[alignedOffset : alignedOffset+len(tensorData)]
	for i, v := range tensorData {
		payloadSlice[i] = byte(v)
	}

	atomic.StoreUint32(&slot.State, SlotStateReady)
	return slotIdx, nil
}
EOF

# 2. Update Python batcher.py to reset slot state and advance atomic tail on expired requests
cat << 'EOF' > /app/python-orchestrator/batcher.py
import os
import mmap
import struct
import time

SHM_PATH = "/dev/shm/tensor_ringbuf.shm"
RINGBUF_CAPACITY = 64
SLOT_HEADER_SIZE = 32
HEADER_SIZE = 16 + (RINGBUF_CAPACITY * SLOT_HEADER_SIZE)

SLOT_STATE_EMPTY = 0
SLOT_STATE_WRITING = 1
SLOT_STATE_READY = 2
SLOT_STATE_PROCESSING = 3
SLOT_STATE_COMPLETED = 4
SLOT_STATE_CANCELLED = 5

class BatchOrchestrator:
    def __init__(self, shm_path=SHM_PATH):
        self.shm_path = shm_path
        self.active_requests = {}
        self.shm_file = None
        self.mm = None

    def open_shm(self):
        if not os.path.exists(self.shm_path):
            return False
        total_size = HEADER_SIZE + (RINGBUF_CAPACITY * 4096) + 4096
        self.shm_file = open(self.shm_path, "r+b")
        self.mm = mmap.mmap(self.shm_file.fileno(), total_size)
        return True

    def close(self):
        if self.mm:
            self.mm.close()
        if self.shm_file:
            self.shm_file.close()

    def get_slot_state(self, slot_idx):
        if not self.mm:
            return None
        offset = 16 + (slot_idx * SLOT_HEADER_SIZE)
        slot_id, state, num_elements, scale_bits, data_offset = struct.unpack_from("<IIIII", self.mm, offset)
        return state

    def set_slot_state(self, slot_idx, state):
        if not self.mm:
            return
        offset = 16 + (slot_idx * SLOT_HEADER_SIZE) + 4
        struct.pack_into("<I", self.mm, offset, state)

    # Fixed clean_expired_requests: Resets slot state to CANCELLED and advances tail
    def clean_expired_requests(self, timeout_sec=2.0):
        now = time.time()
        expired = []
        for req_id, (slot_idx, start_time) in list(self.active_requests.items()):
            if now - start_time > timeout_sec:
                expired.append(req_id)
                if self.mm:
                    self.set_slot_state(slot_idx, SLOT_STATE_CANCELLED)
                    # Advance tail in header to prevent ringbuffer stall
                    struct.pack_into("<I", self.mm, 4, slot_idx)
                del self.active_requests[req_id]
        return expired

    def track_request(self, req_id, slot_idx):
        self.active_requests[req_id] = (slot_idx, time.time())

if __name__ == "__main__":
    orch = BatchOrchestrator()
    if orch.open_shm():
        print("BatchOrchestrator connected to shared memory.")
    else:
        print("Waiting for shared memory creation...")
EOF

# 3. Rebuild all components
chmod +x /app/build_all.sh
/app/build_all.sh

echo "=== Oracle Reference Solution Applied Successfully ==="
