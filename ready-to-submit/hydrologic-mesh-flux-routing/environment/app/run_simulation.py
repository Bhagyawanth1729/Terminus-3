#!/usr/bin/env python3
import os
import sys
import argparse
from watershed.mesh import WatershedMesh
from watershed.forcing import MeteorologicalForcing
from watershed.orchestrator import SimulationOrchestrator
from watershed.hydrograph import evaluate_simulation_results, write_output_netcdf, save_metrics_json


def main():
    parser = argparse.ArgumentParser(description="Catchment Hydrologic Mesh Simulation Runner")
    parser.add_argument("--config", default="/app/data/basin_config.json", help="Path to basin config JSON")
    parser.add_argument("--mesh", default="/app/data/mesh_tin.json", help="Path to mesh TIN JSON")
    parser.add_argument("--forcing", default="/app/data/rainfall_forcing.nc", help="Path to rainfall forcing NetCDF")
    parser.add_argument("--output-nc", default="/app/output/watershed_discharge.nc", help="Output NetCDF path")
    parser.add_argument("--output-json", default="/app/output/summary_metrics.json", help="Output JSON path")
    parser.add_argument("--solver", default="/app/rust_solver/target/release/rust_solver", help="Path to compiled solver binary")
    args = parser.parse_args()

    # Resolve relative paths if run locally
    app_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isabs(args.config):
        args.config = os.path.join(app_dir, args.config)
    if not os.path.isabs(args.mesh):
        args.mesh = os.path.join(app_dir, args.mesh)
    if not os.path.isabs(args.forcing):
        args.forcing = os.path.join(app_dir, args.forcing)
    if not os.path.isabs(args.solver):
        args.solver = os.path.join(app_dir, args.solver)
    if not os.path.isabs(args.output_nc):
        args.output_nc = os.path.join(app_dir, args.output_nc)
    if not os.path.isabs(args.output_json):
        args.output_json = os.path.join(app_dir, args.output_json)

    ref_hydrograph_path = os.path.join(os.path.dirname(args.config), "reference_hydrograph.json")

    print(f"Loading mesh from: {args.mesh}")
    mesh = WatershedMesh(args.config, args.mesh)
    print(f"Mesh loaded: {mesh.num_cells} triangular cells, {len(mesh.outlet_ids)} outlet points.")

    print(f"Loading forcing from: {args.forcing}")
    forcing = MeteorologicalForcing(args.forcing, mesh.num_cells)
    print(f"Forcing loaded: {forcing.num_timesteps} timesteps (dt = {forcing.dt}s).")

    print(f"Launching simulation orchestrator using solver: {args.solver}")
    orchestrator = SimulationOrchestrator(args.solver, mesh, forcing)
    sim_data = orchestrator.run()

    print("Evaluating hydrologic metrics...")
    metrics = evaluate_simulation_results(sim_data, ref_hydrograph_path)

    print(f"Simulation Summary:")
    print(f"  - Peak Discharge: {metrics['peak_discharge_m3s']:.3f} m3/s")
    print(f"  - Total Runoff Volume: {metrics['total_runoff_volume_m3']:.2f} m3")
    print(f"  - Mass Balance Error: {metrics['mass_balance_error_percent']:.6f} %")
    print(f"  - Nash-Sutcliffe Efficiency (NSE): {metrics['nse']:.4f}")

    print(f"Writing output NetCDF: {args.output_nc}")
    write_output_netcdf(args.output_nc, sim_data["time_seconds"], sim_data["discharge"], metrics["cumulative_volume_series"])

    print(f"Writing summary metrics: {args.output_json}")
    save_metrics_json(args.output_json, metrics)

    forcing.close()
    print("Simulation complete.")


if __name__ == "__main__":
    main()
