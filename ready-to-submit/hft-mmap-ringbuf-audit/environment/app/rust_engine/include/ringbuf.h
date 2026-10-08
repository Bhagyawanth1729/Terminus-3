#ifndef RINGBUF_H
#define RINGBUF_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint64_t order_id;
    int64_t  price_scaled;
    uint64_t quantity;
    uint64_t timestamp_ns;
} TradeRecord;

int32_t init_ring_buffer(const char* shm_path, uint32_t capacity);
int32_t push_trade_record(const char* shm_path, uint64_t order_id, int64_t price_scaled, uint64_t quantity, uint64_t timestamp_ns);
uintptr_t create_reader_handle(const char* shm_path);
int32_t read_next_trade(uintptr_t handle_ptr, TradeRecord* out_record);
void free_reader_handle(uintptr_t handle_ptr);
uint64_t get_active_reader_count(void);

#ifdef __cplusplus
}
#endif

#endif // RINGBUF_H
