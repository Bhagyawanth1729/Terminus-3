import os
import json
import numpy as np
import netCDF4 as nc
from typing import Dict, Any


def evaluate_simulation_results(sim_data: Dict[str, Any], reference_hydrograph_path: str = None) -> Dict[str, Any]:
    time_arr = sim_data["time_seconds"]
    discharge_arr = sim_data["discharge"]
    storage_arr = sim_data["storage_volumes"]
    inflow_arr = sim_data["inflow_volumes"]
    outflow_arr = sim_data["outflow_volumes"]

    total_inflow = float(np.sum(inflow_arr))
    total_outflow = float(np.sum(outflow_arr))
    delta_storage = float(storage_arr[-1] - storage_arr[0])

    # Mass balance relative error: |Delta S - (V_in - V_out)| / V_in
    if total_inflow > 1e-6:
        mass_error = abs(delta_storage - (total_inflow - total_outflow)) / total_inflow
        mass_error_pct = mass_error * 100.0
    else:
        mass_error_pct = 0.0

    peak_q = float(np.max(discharge_arr))
    cum_vol = np.cumsum(discharge_arr * (time_arr[1] - time_arr[0] if len(time_arr) > 1 else 10.0))
    total_vol = float(cum_vol[-1]) if len(cum_vol) > 0 else 0.0

    # Calculate Nash-Sutcliffe Efficiency (NSE) against reference gauge if available
    nse_score = 0.0
    if reference_hydrograph_path and os.path.exists(reference_hydrograph_path):
        with open(reference_hydrograph_path, "r") as f:
            ref_data = json.load(f)
        ref_q = np.array(ref_data.get("discharge_m3s", []), dtype=np.float64)
        if len(ref_q) == len(discharge_arr):
            mean_ref = np.mean(ref_q)
            numerator = np.sum((ref_q - discharge_arr) ** 2)
            denominator = np.sum((ref_q - mean_ref) ** 2)
            if denominator > 1e-9:
                nse_score = float(1.0 - (numerator / denominator))
            else:
                nse_score = 1.0

    return {
        "peak_discharge_m3s": peak_q,
        "total_runoff_volume_m3": total_vol,
        "mass_balance_error_percent": mass_error_pct,
        "nse": nse_score,
        "cumulative_volume_series": cum_vol,
    }


def write_output_netcdf(output_nc_path: str, time_arr: np.ndarray, discharge_arr: np.ndarray, cum_vol_arr: np.ndarray):
    os.makedirs(os.path.dirname(os.path.abspath(output_nc_path)), exist_ok=True)
    if os.path.exists(output_nc_path):
        os.remove(output_nc_path)

    ds = nc.Dataset(output_nc_path, "w", format="NETCDF4")
    try:
        ds.Conventions = "CF-1.8"
        ds.title = "Catchment Outlet Hydrograph and Runoff Volume"
        ds.source = "Terminus 3 Hydrologic Mesh Flux Routing Simulation"

        ds.createDimension("time", len(time_arr))

        v_time = ds.createVariable("time", "f8", ("time",))
        v_time.units = "seconds since simulation start"
        v_time.long_name = "Simulation elapsed time"
        v_time[:] = time_arr

        v_q = ds.createVariable("discharge", "f8", ("time",))
        v_q.units = "m3 s-1"
        v_q.long_name = "Catchment outlet discharge hydrograph"
        v_q[:] = discharge_arr

        v_vol = ds.createVariable("cumulative_volume", "f8", ("time",))
        v_vol.units = "m3"
        v_vol.long_name = "Cumulative routed discharge volume"
        v_vol[:] = cum_vol_arr
    finally:
        ds.close()


def save_metrics_json(output_json_path: str, metrics: Dict[str, Any]):
    os.makedirs(os.path.dirname(os.path.abspath(output_json_path)), exist_ok=True)
    clean_metrics = {
        "peak_discharge_m3s": float(metrics["peak_discharge_m3s"]),
        "total_runoff_volume_m3": float(metrics["total_runoff_volume_m3"]),
        "mass_balance_error_percent": float(metrics["mass_balance_error_percent"]),
        "nse": float(metrics["nse"]),
    }
    with open(output_json_path, "w") as f:
        json.dump(clean_metrics, f, indent=2)
