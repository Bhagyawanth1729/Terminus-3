use crate::types::{CellState, MeshCell, MeshDefinition, MeshNeighbor};
use std::fs::File;
use std::io::BufReader;
use std::path::Path;

pub struct TriangularMesh {
    pub cells: Vec<MeshCell>,
    pub outlet_ids: Vec<usize>,
}

impl TriangularMesh {
    pub fn load_from_json<P: AsRef<Path>>(path: P) -> Result<Self, Box<dyn std::error::Error>> {
        let file = File::open(path)?;
        let reader = BufReader::new(file);
        let def: MeshDefinition = serde_json::from_reader(reader)?;
        Ok(Self {
            cells: def.cells,
            outlet_ids: def.outlet_ids,
        })
    }

    pub fn total_storage_volume(&self) -> f64 {
        self.cells
            .iter()
            .map(|c| c.state.water_depth * c.state.area)
            .sum()
    }

    pub fn total_catchment_area(&self) -> f64 {
        self.cells.iter().map(|c| c.state.area).sum()
    }
}
