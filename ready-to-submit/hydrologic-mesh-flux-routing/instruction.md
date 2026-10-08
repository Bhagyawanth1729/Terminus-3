A coupled hydrologic simulation framework (`/app`) models surface runoff and kinematic-diffusive wave routing across an irregular triangular mesh (TIN) for a mountainous catchment basin. The pipeline consists of a Python watershed preprocessor/orchestrator (`/app/watershed/`) that streams meteorological forcing and subcatchment boundary states over shared memory IPC to a high-performance numerical Rust solver (`/app/rust_solver/`).

The current simulation run fails physical verification checks. Run `/app/build.sh` to compile the solver and execute the end-to-end simulation via `/app/run_simulation.py`. Ensure the following requirements are satisfied:

1. **Mass Conservation**: Total catchment mass balance across all mesh cells must be strictly conserved. The relative mass conservation error:
   $$\text{Error} = \frac{|\Delta S - (V_{\text{in}} - V_{\text{out}})|}{V_{\text{in}}}$$
   must be less than $10^{-4}\%$ ($10^{-6}$ fractional error) over the entire simulation duration, with no negative cell water depths ($h \ge 0.0\text{ m}$).
2. **Hydrograph Accuracy**: The simulated basin outlet hydrograph must match the expected hydrodynamic response, achieving a Nash-Sutcliffe Efficiency (NSE) $\ge 0.98$ and zero peak arrival lag error compared to calibrated gauge records.
3. **Output Files**: The simulation must generate:
   - `/app/output/watershed_discharge.nc`: A CF-1.8 compliant NetCDF file containing the `time` dimension, `discharge` variable in $\text{m}^3/\text{s}$, and `cumulative_volume` variable in $\text{m}^3$.
   - `/app/output/summary_metrics.json`: A JSON summary containing `{"peak_discharge_m3s": float, "total_runoff_volume_m3": float, "mass_balance_error_percent": float, "nse": float}`.
4. **Rebuild & Generalization**: The Rust solver must build cleanly via `/app/build.sh` (or `cargo build --release` in `/app/rust_solver`) and generalize to unseen storm hydrographs without numerical divergence or runtime crashes.
