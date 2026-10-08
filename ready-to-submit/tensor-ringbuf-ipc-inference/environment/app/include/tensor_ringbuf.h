#ifndef TENSOR_RINGBUF_H
#define TENSOR_RINGBUF_H

#include <stdint.h>
#include <stdatomic.h>

#define RINGBUF_SHM_NAME "/dev/shm/tensor_ringbuf.shm"
#define RINGBUF_CAPACITY 64
#define SLOT_DATA_MAX_BYTES 4096
#define SIMD_ALIGNMENT 64

// Slot states
#define SLOT_STATE_EMPTY      0
#define SLOT_STATE_WRITING    1
#define SLOT_STATE_READY      2
#define SLOT_STATE_PROCESSING 3
#define SLOT_STATE_COMPLETED  4
#define SLOT_STATE_CANCELLED  5

typedef struct {
    uint32_t slot_id;
    uint32_t state;           // atomic state
    uint32_t num_elements;    // number of int8 elements
    uint32_t scale_factor_bits; // float32 bits (IEEE-754)
    uint32_t data_offset;     // byte offset from ringbuffer base (MUST be 64-byte aligned)
    uint32_t pad[3];
} SlotHeader;

typedef struct {
    uint32_t head;            // atomic write head
    uint32_t tail;            // atomic read/completion tail
    uint32_t capacity;        // RINGBUF_CAPACITY
    uint32_t total_processed; // total processed counter
    SlotHeader slots[RINGBUF_CAPACITY];
    // Payload data follows slots array
} RingBufferHeader;

#endif // TENSOR_RINGBUF_H
