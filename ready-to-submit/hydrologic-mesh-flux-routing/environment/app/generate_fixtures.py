#!/usr/bin/env python3
"""
Deterministically generates catchment basin configuration, mesh TIN, reference hydrographs,
and NetCDF rainfall forcing datasets for hydrologic-mesh-flux-routing.
"""
import os
import json
import math
import numpy as np


def generate_mesh_and_config(data_dir: str):
    os.makedirs(data_dir, exist_ok=True)

    # 1. Generate 32-cell Triangular Irregular Network (TIN)
    # Cells arranged on a digital elevation slope descending towards outlet cell 0
    num_cells = 32
    cells = []
    outlet_ids = [0]

    # Create coordinate grid for centroids
    # Grid 4x8
    nx, ny = 4, 8
    coords = []
    for j in range(ny):
        for i in range(nx):
            x = i * 80.0 + (40.0 if j % 2 == 1 else 0.0)
            y = j * 80.0
            coords.append((x, y))

    for idx in range(num_cells):
        x, y = coords[idx]
        # Elevation decreases as y decreases and x approaches outlet (0, 0)
        dist_to_outlet = math.sqrt(x**2 + y**2)
        elev = 150.0 + 0.45 * y + 0.25 * x + 5.0 * math.sin(idx * 0.7)
        area = 7500.0 + 500.0 * math.cos(idx * 1.3)
        manning_n = 0.038 + 0.005 * math.sin(idx * 0.9)
        slope = max(0.015, (elev - 150.0) / max(dist_to_outlet, 50.0))

        # Find topological neighbors within distance 120m
        neighbors = []
        for n_idx in range(num_cells):
            if n_idx == idx:
                continue
            nx_c, ny_c = coords[n_idx]
            d = math.hypot(nx_c - x, ny_c - y)
            if d <= 125.0:
                neighbors.append({
                    "neighbor_id": n_idx,
                    "edge_length": 65.0 + 10.0 * math.sin(idx + n_idx),
                    "centroid_dist": d
                })

        is_outlet = (idx == 0)
        cells.append({
            "id": idx,
            "state": {
                "elevation": round(elev, 2),
                "area": round(area, 2),
                "manning_n": round(manning_n, 4),
                "slope": round(slope, 4),
                "water_depth": 0.0,
                "flags": 0,
                "pad": 0
            },
            "neighbors": neighbors,
            "is_outlet": is_outlet
        })

    mesh_data = {
        "num_cells": num_cells,
        "outlet_ids": outlet_ids,
        "cells": cells
    }

    mesh_path = os.path.join(data_dir, "mesh_tin.json")
    with open(mesh_path, "w") as f:
        json.dump(mesh_data, f, indent=2)
    print(f"Generated {mesh_path}")

    # 2. Basin Config
    config = {
        "basin_name": "Clearwater Creek Mountain Catchment",
        "basin_area_m2": sum(c["state"]["area"] for c in cells),
        "mesh_file": "data/mesh_tin.json",
        "forcing_file": "data/rainfall_forcing.nc",
        "channel_routing": {
            "reach_lag_seconds": 40.0,
            "manning_n_channel": 0.032
        }
    }
    config_path = os.path.join(data_dir, "basin_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Generated {config_path}")

    return mesh_data, config


def generate_netcdf_forcing(nc_path: str, num_cells: int, storm_type: str = "standard"):
    try:
        import netCDF4 as nc
    except ImportError:
        print(f"netCDF4 not available in current environment; skipping {nc_path} generation until Docker build.")
        return

    os.makedirs(os.path.dirname(os.path.abspath(nc_path)), exist_ok=True)
    if os.path.exists(nc_path):
        os.remove(nc_path)

    # 120 timesteps of dt = 10s (total 1200 seconds = 20 minutes)
    num_timesteps = 120
    dt = 10.0
    time_arr = np.arange(num_timesteps, dtype=np.float64) * dt

    precip = np.zeros((num_timesteps, num_cells), dtype=np.float64)
    infil = np.zeros((num_timesteps, num_cells), dtype=np.float64)

    if storm_type == "standard":
        # Unimodal convective storm peaking at t = 350s
        for t_idx, t in enumerate(time_arr):
            # Intensity in mm/hr converted to m/s: 1 mm/hr = 1e-3 / 3600 m/s
            intensity_mm_hr = 65.0 * math.exp(-((t - 350.0) / 120.0)**2)
            intensity_m_s = (intensity_mm_hr * 1e-3) / 3600.0
            precip[t_idx, :] = intensity_m_s

            # Horton infiltration decay: f(t) = fc + (f0 - fc) * exp(-k * t)
            # f0 = 25 mm/hr, fc = 5 mm/hr, k = 0.005 s^-1
            f_t_mm_hr = 5.0 + 20.0 * math.exp(-0.004 * t)
            infil[t_idx, :] = (f_t_mm_hr * 1e-3) / 3600.0
    else:
        # Extreme bimodal storm for holdout tests
        for t_idx, t in enumerate(time_arr):
            peak1 = 85.0 * math.exp(-((t - 250.0) / 90.0)**2)
            peak2 = 110.0 * math.exp(-((t - 650.0) / 110.0)**2)
            intensity_mm_hr = peak1 + peak2
            precip[t_idx, :] = (intensity_mm_hr * 1e-3) / 3600.0

            f_t_mm_hr = 6.0 + 15.0 * math.exp(-0.005 * t)
            infil[t_idx, :] = (f_t_mm_hr * 1e-3) / 3600.0

    ds = nc.Dataset(nc_path, "w", format="NETCDF4")
    try:
        ds.Conventions = "CF-1.8"
        ds.title = f"Meteorological Forcing: {storm_type}"
        ds.createDimension("time", num_timesteps)
        ds.createDimension("cell", num_cells)

        v_time = ds.createVariable("time", "f8", ("time",))
        v_time.units = "seconds since simulation start"
        v_time[:] = time_arr

        v_p = ds.createVariable("precipitation", "f8", ("time", "cell"))
        v_p.units = "m s-1"
        v_p.long_name = "Surface rainfall precipitation intensity"
        v_p[:] = precip

        v_inf = ds.createVariable("infiltration", "f8", ("time", "cell"))
        v_inf.units = "m s-1"
        v_inf.long_name = "Soil infiltration capacity"
        v_inf[:] = infil
    finally:
        ds.close()
    print(f"Generated NetCDF forcing: {nc_path}")


def simulate_reference_hydrograph(mesh_data: dict, data_dir: str):
    """
    Computes exact physical reference hydrograph using analytical/correct 2D kinematic wave equations.
    """
    cells = mesh_data["cells"]
    num_cells = len(cells)
    dt = 10.0
    num_timesteps = 120
    time_arr = [i * dt for i in range(num_timesteps)]

    # Cell states
    elevations = [c["state"]["elevation"] for c in cells]
    areas = [c["state"]["area"] for c in cells]
    manning_ns = [c["state"]["manning_n"] for c in cells]
    slopes = [c["state"]["slope"] for c in cells]
    water_depths = [0.0] * num_cells

    raw_discharges = []

    for t_idx in range(num_timesteps):
        t = t_idx * dt
        p_rate = (65.0 * math.exp(-((t - 350.0) / 120.0)**2) * 1e-3) / 3600.0
        inf_rate = ((5.0 + 20.0 * math.exp(-0.004 * t)) * 1e-3) / 3600.0
        net_p = max(0.0, p_rate - inf_rate)

        # Inflow
        for i in range(num_cells):
            water_depths[i] += net_p * dt

        # Inter-cell flux
        delta_v = [0.0] * num_cells
        outlet_q = 0.0

        for i in range(num_cells):
            h_i = water_depths[i]
            if h_i <= 1e-6:
                continue

            z_i = elevations[i]
            wse_i = z_i + h_i
            n_i = manning_ns[i]

            cell_outflow_rates = []
            for nb in cells[i]["neighbors"]:
                nb_id = nb["neighbor_id"]
                wse_j = elevations[nb_id] + water_depths[nb_id]
                if wse_i > wse_j:
                    s_f = (wse_i - wse_j) / nb["centroid_dist"]
                    if s_f > 1e-6:
                        v = (1.0 / n_i) * (h_i ** (2.0 / 3.0)) * math.sqrt(s_f)
                        q = max(0.0, v * h_i * nb["edge_length"])
                        cell_outflow_rates.append((nb_id, q))

            # Outlet flux
            q_outlet = 0.0
            if cells[i]["is_outlet"]:
                s = max(1e-4, slopes[i])
                v = (1.0 / n_i) * (h_i ** (2.0 / 3.0)) * math.sqrt(s)
                q_outlet = v * h_i * math.sqrt(areas[i])

            # Apply strict volume limiter to cell i
            total_req_out_vol = (sum(q for _, q in cell_outflow_rates) + q_outlet) * dt
            avail_vol = water_depths[i] * areas[i]
            limiter = 1.0
            if total_req_out_vol > avail_vol and total_req_out_vol > 1e-12:
                limiter = avail_vol / total_req_out_vol

            for nb_id, q in cell_outflow_rates:
                q_eff = q * limiter
                vol = q_eff * dt
                delta_v[i] -= vol
                delta_v[nb_id] += vol

            if q_outlet > 0:
                q_out_eff = q_outlet * limiter
                vol = q_out_eff * dt
                delta_v[i] -= vol
                outlet_q += q_out_eff

        for i in range(num_cells):
            new_v = max(0.0, water_depths[i] * areas[i] + delta_v[i])
            water_depths[i] = new_v / areas[i]

        raw_discharges.append(outlet_q)

    # Channel routing lag of 40s (4 timesteps)
    lag_steps = int(round(40.0 / dt))
    routed_q = [0.0] * num_timesteps
    for idx in range(lag_steps, num_timesteps):
        routed_q[idx] = raw_discharges[idx - lag_steps]

    ref_data = {
        "time_seconds": time_arr,
        "discharge_m3s": routed_q,
        "peak_discharge_m3s": max(routed_q),
        "total_runoff_volume_m3": sum(q * dt for q in routed_q),
    }

    ref_path = os.path.join(data_dir, "reference_hydrograph.json")
    with open(ref_path, "w") as f:
        json.dump(ref_data, f, indent=2)
    print(f"Generated reference hydrograph: {ref_path}")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    mesh_data, config = generate_mesh_and_config(data_dir)
    simulate_reference_hydrograph(mesh_data, data_dir)

    # Rainfall forcing
    forcing_nc = os.path.join(data_dir, "rainfall_forcing.nc")
    generate_netcdf_forcing(forcing_nc, len(mesh_data["cells"]), "standard")

    # Holdout forcing for tests
    holdout_nc = os.path.abspath(os.path.join(base_dir, "../../tests/holdout/storm_extreme.nc"))
    generate_netcdf_forcing(holdout_nc, len(mesh_data["cells"]), "extreme")
