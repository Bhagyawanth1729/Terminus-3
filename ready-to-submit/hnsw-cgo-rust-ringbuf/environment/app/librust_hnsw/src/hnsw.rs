use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

pub static ACTIVE_SEARCH_CTX_COUNT: AtomicUsize = AtomicUsize::new(0);

#[derive(Clone)]
pub struct VectorPoint {
    pub id: u64,
    pub data: Vec<f32>,
}

pub struct HnswIndex {
    pub dim: usize,
    pub max_elements: usize,
    pub points: Mutex<HashMap<u64, VectorPoint>>,
    pub point_list: Mutex<Vec<VectorPoint>>,
}

impl HnswIndex {
    pub fn new(dim: usize, max_elements: usize) -> Self {
        HnswIndex {
            dim,
            max_elements,
            points: Mutex::new(HashMap::new()),
            point_list: Mutex::new(Vec::new()),
        }
    }

    pub fn add_point(&self, id: u64, vector: Vec<f32>) -> bool {
        if vector.len() != self.dim {
            return false;
        }
        let pt = VectorPoint { id, data: vector };
        let mut pts = self.points.lock().unwrap();
        let mut pt_list = self.point_list.lock().unwrap();
        pts.insert(id, pt.clone());
        pt_list.push(pt);
        true
    }

    pub fn search(&self, query: &[f32], k: usize) -> Vec<(u64, f32)> {
        if query.len() != self.dim {
            return Vec::new();
        }

        let pts = self.point_list.lock().unwrap();
        let mut scored: Vec<(u64, f32)> = pts
            .iter()
            .map(|p| {
                let sim = cosine_similarity(query, &p.data);
                (p.id, sim)
            })
            .collect();

        // Sort descending by score
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(k);
        scored
    }
}

pub struct SearchContext {
    pub index_ptr: *const HnswIndex,
    pub id: usize,
}

impl SearchContext {
    pub fn new(index_ptr: *const HnswIndex) -> Self {
        let count = ACTIVE_SEARCH_CTX_COUNT.fetch_add(1, Ordering::SeqCst) + 1;
        SearchContext { index_ptr, id: count }
    }
}

impl Drop for SearchContext {
    fn drop(&mut self) {
        ACTIVE_SEARCH_CTX_COUNT.fetch_sub(1, Ordering::SeqCst);
    }
}

pub fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    let mut dot = 0.0f32;
    let mut norm_a = 0.0f32;
    let mut norm_b = 0.0f32;

    for i in 0..a.len() {
        dot += a[i] * b[i];
        norm_a += a[i] * a[i];
        norm_b += b[i] * b[i];
    }

    if norm_a == 0.0 || norm_b == 0.0 {
        0.0
    } else {
        dot / (norm_a.sqrt() * norm_b.sqrt())
    }
}
