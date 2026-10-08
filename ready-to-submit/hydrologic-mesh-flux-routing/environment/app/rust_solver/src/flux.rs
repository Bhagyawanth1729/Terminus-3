use crate::mesh::TriangularMesh;
use crate::types::{StepForcing, StepResult};

pub fn compute_step(
    mesh: &mut TriangularMesh,
    forcing: &StepForcing,
    step_index: usize,
) -> StepResult {
    let dt = forcing.dt_seconds;
    let n_cells = mesh.cells.len();
    let mut net_inflow_vol = 0.0;
    let mut net_outflow_vol = 0.0;
    let mut total_outlet_q = 0.0;

    // Apply precipitation and infiltration
    for (i, cell) in mesh.cells.iter_mut().enumerate() {
        let p = forcing.precipitation_m_per_s.get(i).copied().unwrap_or(0.0);
        let inf = forcing.infiltration_m_per_s.get(i).copied().unwrap_or(0.0);
        let net_p = (p - inf).max(0.0);
        let added_vol = net_p * cell.state.area * dt;
        cell.state.water_depth += net_p * dt;
        net_inflow_vol += added_vol;
    }

    // Compute inter-cell fluxes
    let mut delta_volumes = vec![0.0f64; n_cells];

    for i in 0..n_cells {
        let cell = &mesh.cells[i];
        let h_i = cell.state.water_depth;
        if h_i <= 1e-6 {
            continue;
        }

        let z_i = cell.state.elevation;
        let wse_i = z_i + h_i;
        let n_i = cell.state.manning_n;

        for nb in &cell.neighbors {
            let neighbor = &mesh.cells[nb.neighbor_id];
            let h_j = neighbor.state.water_depth;
            let z_j = neighbor.state.elevation;
            let wse_j = z_j + h_j;

            if wse_i > wse_j {
                let s_f = (wse_i - wse_j) / nb.centroid_dist;
                if s_f > 1e-6 {
                    let v = (1.0 / n_i) * h_i.powf(2.0 / 3.0) * s_f.sqrt();
                    let q = (v * h_i * nb.edge_length).max(0.0);
                    let transfer_vol = q * dt;

                    // Unconstrained flux transfer without limiting against total available cell volume
                    delta_volumes[i] -= transfer_vol;
                    delta_volumes[nb.neighbor_id] += transfer_vol;
                }
            }
        }

        if cell.is_outlet {
            let slope = cell.state.slope.max(1e-4);
            let v = (1.0 / n_i) * h_i.powf(2.0 / 3.0) * slope.sqrt();
            let q_out = v * h_i * (cell.state.area).sqrt();
            let out_vol = q_out * dt;
            delta_volumes[i] -= out_vol;
            net_outflow_vol += out_vol;
            total_outlet_q += q_out;
        }
    }

    // Update depths (broken: clamps negative depth without conserving mass)
    for i in 0..n_cells {
        let cell = &mut mesh.cells[i];
        let new_vol = cell.state.water_depth * cell.state.area + delta_volumes[i];
        if new_vol < 0.0 {
            cell.state.water_depth = 0.0;
        } else {
            cell.state.water_depth = new_vol / cell.state.area;
        }
    }

    let mut max_h = 0.0f64;
    let mut min_h = f64::MAX;
    for cell in &mesh.cells {
        max_h = max_h.max(cell.state.water_depth);
        min_h = min_h.min(cell.state.water_depth);
    }
    if min_h == f64::MAX {
        min_h = 0.0;
    }

    let total_storage = mesh.total_storage_volume();

    StepResult {
        step_index,
        outlet_discharge_m3s: total_outlet_q,
        total_storage_volume_m3: total_storage,
        net_inflow_volume_m3: net_inflow_vol,
        net_outflow_volume_m3: net_outflow_vol,
        max_water_depth_m: max_h,
        min_water_depth_m: min_h,
    }
}
