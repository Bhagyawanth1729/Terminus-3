#!/bin/bash
set -euo pipefail

echo "Applying fix for hydrologic-mesh-flux-routing..."

# 1. Fix Defect 1: Struct field alignment in /app/watershed/mesh.py
# Align Python struct packing order with Rust's #[repr(C)] CellState:
# (elevation, area, manning_n, slope, water_depth, flags, pad)
python3 - << 'EOF'
with open("/app/watershed/mesh.py", "r") as f:
    content = f.read()

old_block = """            packed = struct.pack(
                "<dddddII",
                float(state["elevation"]),
                float(state["area"]),
                float(state["slope"]),     # BROKEN: slope packed before manning_n
                float(state["manning_n"]), # BROKEN: manning_n packed after slope
                float(state["water_depth"]),
                int(state.get("flags", 0)),
                int(state.get("pad", 0)),
            )"""

new_block = """            packed = struct.pack(
                "<dddddII",
                float(state["elevation"]),
                float(state["area"]),
                float(state["manning_n"]),
                float(state["slope"]),
                float(state["water_depth"]),
                int(state.get("flags", 0)),
                int(state.get("pad", 0)),
            )"""

if old_block in content:
    content = content.replace(old_block, new_block)
else:
    # General replacement if whitespace differs
    content = content.replace('float(state["slope"]),\n                float(state["manning_n"])', 'float(state["manning_n"]),\n                float(state["slope"])')

with open("/app/watershed/mesh.py", "w") as f:
    f.write(content)
print("Updated /app/watershed/mesh.py struct field alignment.")
EOF

# 2. Fix Defect 2: Rust flux limiter in /app/rust_solver/src/flux.rs
# Implement volume-conserving flux limiter to enforce non-negative water depth and mass conservation
cat << 'EOF' > /app/rust_solver/src/flux.rs
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

    // 1. Apply precipitation and infiltration
    for (i, cell) in mesh.cells.iter_mut().enumerate() {
        let p = forcing.precipitation_m_per_s.get(i).copied().unwrap_or(0.0);
        let inf = forcing.infiltration_m_per_s.get(i).copied().unwrap_or(0.0);
        let net_p = (p - inf).max(0.0);
        let added_vol = net_p * cell.state.area * dt;
        cell.state.water_depth += net_p * dt;
        net_inflow_vol += added_vol;
    }

    // 2. Compute inter-cell fluxes with conservative volume flux limiting
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

        let mut neighbor_transfers = Vec::new();
        let mut sum_outflow_q = 0.0f64;

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
                    neighbor_transfers.push((nb.neighbor_id, q));
                    sum_outflow_q += q;
                }
            }
        }

        let mut q_outlet = 0.0f64;
        if cell.is_outlet {
            let slope = cell.state.slope.max(1e-4);
            let v = (1.0 / n_i) * h_i.powf(2.0 / 3.0) * slope.sqrt();
            q_outlet = v * h_i * (cell.state.area).sqrt();
            sum_outflow_q += q_outlet;
        }

        // Apply strict flux limiter based on total available cell water volume
        let avail_vol = cell.state.water_depth * cell.state.area;
        let req_vol = sum_outflow_q * dt;
        let limiter = if req_vol > avail_vol && req_vol > 1e-12 {
            avail_vol / req_vol
        } else {
            1.0
        };

        for (nb_id, q) in neighbor_transfers {
            let eff_vol = q * limiter * dt;
            delta_volumes[i] -= eff_vol;
            delta_volumes[nb_id] += eff_vol;
        }

        if q_outlet > 0.0 {
            let eff_out_vol = q_outlet * limiter * dt;
            delta_volumes[i] -= eff_out_vol;
            net_outflow_vol += eff_out_vol;
            total_outlet_q += q_outlet * limiter;
        }
    }

    // 3. Update water depths
    for i in 0..n_cells {
        let cell = &mut mesh.cells[i];
        let new_vol = (cell.state.water_depth * cell.state.area + delta_volumes[i]).max(0.0);
        cell.state.water_depth = new_vol / cell.state.area;
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
EOF
echo "Updated /app/rust_solver/src/flux.rs with conservative volume flux limiter."

# 3. Fix Defect 3: Timestep delta scaling in /app/watershed/orchestrator.py
python3 - << 'EOF'
with open("/app/watershed/orchestrator.py", "r") as f:
    content = f.read()

old_lag = "lag_steps = int(channel_lag_sec / (dt / 1000.0))"
new_lag = "lag_steps = int(round(channel_lag_sec / dt))"

if old_lag in content:
    content = content.replace(old_lag, new_lag)

with open("/app/watershed/orchestrator.py", "w") as f:
    f.write(content)
print("Updated /app/watershed/orchestrator.py channel routing lag calculation.")
EOF

# 4. Rebuild Rust binary in release mode
echo "Rebuilding Rust solver..."
/app/build.sh

# 5. Run end-to-end simulation
echo "Executing hydrologic simulation..."
python3 /app/run_simulation.py

echo "Oracle fix completed successfully."
