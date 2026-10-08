#ifndef HNSW_CFFI_H
#define HNSW_CFFI_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint64_t node_id;
    float distance;
} hnsw_result_c;

typedef struct {
    uint32_t query_id;
    uint64_t node_id;
    float distance;
    uint32_t vector_dim;
    float vector_data[16];
} ring_item_c;

typedef void* HnswIndexPtr;
typedef void* SearchCtxPtr;
typedef void* RingBufPtr;

HnswIndexPtr hnsw_init_index(uint32_t dim, size_t max_elements);
int32_t hnsw_add_point(HnswIndexPtr index, uint64_t node_id, const float* vector_data);
size_t hnsw_search(HnswIndexPtr index, const float* query_data, size_t k, hnsw_result_c* results_out);
SearchCtxPtr hnsw_create_search_ctx(HnswIndexPtr index);
void hnsw_free_search_ctx(SearchCtxPtr ctx);
size_t hnsw_get_active_ctx_count(void);

RingBufPtr hnsw_ringbuf_init(const char* path, uint32_t capacity);
int32_t hnsw_ringbuf_write(RingBufPtr rb, const ring_item_c* item);
void hnsw_ringbuf_free(RingBufPtr rb);

#ifdef __cplusplus
}
#endif

#endif // HNSW_CFFI_H
