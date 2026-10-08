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
	HeaderSize     = 16 + (RingCapacity * SlotHeaderSize) // 16 bytes for head, tail, capacity, total_processed
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

// BUG 1 (Original): Calculates unaligned data offset instead of 64-byte aligned boundary.
// BUG 2 (Original): Uses BigEndian byte order for scale factor bits instead of LittleEndian.
func (rb *SharedRingBuffer) WriteTensor(slotID uint32, tensorData []int8, scaleFactor float32) (uint32, error) {
	headPtr := (*uint32)(unsafe.Pointer(&rb.data[0]))
	slotIdx := atomic.AddUint32(headPtr, 1) % RingCapacity

	slot := rb.getSlotHeaderPtr(slotIdx)
	
	// Wait/check if slot is free
	if atomic.LoadUint32(&slot.State) != SlotStateEmpty && atomic.LoadUint32(&slot.State) != SlotStateCompleted && atomic.LoadUint32(&slot.State) != SlotStateCancelled {
		// Retry once with CAS or return busy
		return 0, fmt.Errorf("ring buffer full or slot %d busy", slotIdx)
	}

	atomic.StoreUint32(&slot.State, SlotStateWriting)
	slot.SlotID = slotID
	slot.NumElements = uint32(len(tensorData))

	// BUG 2: Storing scale factor bits using BigEndian
	scaleBits := math.Float32bits(scaleFactor)
	var scaleBuf [4]byte
	binary.BigEndian.PutUint32(scaleBuf[:], scaleBits)
	slot.ScaleFactorBits = *(*uint32)(unsafe.Pointer(&scaleBuf[0]))

	// BUG 1: Unaligned offset computation (offset ends up with non-64-byte alignment)
	rawOffset := HeaderSize + int(slotIdx)*SlotDataMaxSize + 17
	slot.DataOffset = uint32(rawOffset)

	// Copy tensor data
	payloadSlice := rb.data[rawOffset : rawOffset+len(tensorData)]
	for i, v := range tensorData {
		payloadSlice[i] = byte(v)
	}

	atomic.StoreUint32(&slot.State, SlotStateReady)
	return slotIdx, nil
}
