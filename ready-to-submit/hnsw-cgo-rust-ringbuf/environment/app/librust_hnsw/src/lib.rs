pub mod hnsw;
pub mod ringbuf;

use hnsw::{HnswIndex, SearchContext, ACTIVE_SEARCH_CTX_COUNT};
use ringbuf::{RingBuffer, RingItemC};
use libc::{c_char, size_t};
use std::sync::atomic::Ordering;

#[repr(C)]
pub struct HnswResultC {
    pub node_id: u64,
    pub distance: f32,
}

#[no_mangle]
pub extern "C" fn hnsw_init_index(dim: u32, max_elements: size_t) -> *mut HnswIndex {
    let index = HnswIndex::new(dim as usize, max_elements as usize);
    Box::into_raw(Box::new(index))
}

#[no_mangle]
pub extern "C" fn hnsw_add_point(index: *mut HnswIndex, id: u64, vector_data: *const f32) -> i32 {
    if index.is_null() || vector_data.is_null() { return 0; }
    let index_ref = unsafe { &*index };
    let slice = unsafe { std::slice::from_raw_parts(vector_data, index_ref.dim) };
    if index_ref.add_point(id, slice.to_vec()) { 1 } else { 0 }
}

#[no_mangle]
pub extern "C" fn hnsw_search(
    index: *mut HnswIndex,
    query_data: *const f32,
    k: size_t,
    results_out: *mut HnswResultC,
) -> size_t {
    if index.is_null() || query_data.is_null() || results_out.is_null() { return 0; }
    let index_ref = unsafe { &*index };
    let query_slice = unsafe { std::slice::from_raw_parts(query_data, index_ref.dim) };

    let results = index_ref.search(query_slice, k as usize);
    let out_slice = unsafe { std::slice::from_raw_parts_mut(results_out, results.len()) };

    for (i, (node_id, score)) in results.iter().enumerate() {
        out_slice[i] = HnswResultC {
            node_id: *node_id,
            distance: *score,
        };
    }

    results.len()
}

#[no_mangle]
pub extern "C" fn hnsw_create_search_ctx(index: *mut HnswIndex) -> *mut SearchContext {
    if index.is_null() { return std::ptr::null_mut(); }
    let ctx = SearchContext::new(index as *const HnswIndex);
    Box::into_raw(Box::new(ctx))
}

#[no_mangle]
pub extern "C" fn hnsw_free_search_ctx(ctx: *mut SearchContext) {
    if !ctx.is_null() {
        unsafe { let _ = Box::from_raw(ctx); }
    }
}

#[no_mangle]
pub extern "C" fn hnsw_get_active_ctx_count() -> size_t {
    ACTIVE_SEARCH_CTX_COUNT.load(Ordering::SeqCst) as size_t
}
