use serde::{Deserialize, Serialize};

#[repr(C)]
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct CellState {
    pub elevation: f64,
    pub area: f64,
    pub manning_n: f64,
    pub slope: f64,
    pub water_depth: f64,
    pub flags: u32,
    pub pad: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeshNeighbor {
    pub neighbor_id: usize,
    pub edge_length: f64,
    pub centroid_dist: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeshCell {
    pub id: usize,
    pub state: CellState,
    pub neighbors: Vec<MeshNeighbor>,
    pub is_outlet: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeshDefinition {
    pub cells: Vec<MeshCell>,
    pub outlet_ids: Vec<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StepForcing {
    pub precipitation_m_per_s: Vec<f64>,
    pub infiltration_m_per_s: Vec<f64>,
    pub dt_seconds: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StepResult {
    pub step_index: usize,
    pub outlet_discharge_m3s: f64,
    pub total_storage_volume_m3: f64,
    pub net_inflow_volume_m3: f64,
    pub net_outflow_volume_m3: f64,
    pub max_water_depth_m: f64,
    pub min_water_depth_m: f64,
}
