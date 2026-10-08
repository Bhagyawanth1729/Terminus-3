"""
Verifier test suite for hydrologic-mesh-flux-routing.
Grades physical mass conservation, hydrograph hydrodynamic fidelity, CF-1.8 metadata compliance,
and holdout storm generalization.
"""
import os
import json
import math
import subprocess
import pytest
import numpy as np
import netCDF4 as nc


OUTPUT_NC_PATH = "/app/output/watershed_discharge.nc"
OUTPUT_JSON_PATH = "/app/output/summary_metrics.json"
REF_HYDROGRAPH_PATH = "/app/data/reference_hydrograph.json"
SOLVER_BIN_PATH = "/app/rust_solver/target/release/rust_solver"
MESH_JSON_PATH = "/app/data/mesh_tin.json"
BASIN_CONFIG_PATH = "/app/data/basin_config.json"
HOLDOUT_FORCING_NC = "/tests/holdout/storm_extreme.nc"


def test_output_files_exist_and_valid():
    """
    Verifies that the required output files exist, are non-empty, and conform to the
    CF-1.8 NetCDF and JSON schemas.
    """
    assert os.path.exists(OUTPUT_NC_PATH), f"Output NetCDF missing at {OUTPUT_NC_PATH}"
    assert os.path.getsize(OUTPUT_NC_PATH) > 0, "Output NetCDF file is empty"
    assert os.path.exists(OUTPUT_JSON_PATH), f"Summary JSON missing at {OUTPUT_JSON_PATH}"

    # Verify JSON structure
    with open(OUTPUT_JSON_PATH, "r") as f:
        metrics = json.load(f)

    required_keys = ["peak_discharge_m3s", "total_runoff_volume_m3", "mass_balance_error_percent", "nse"]
    for key in required_keys:
        assert key in metrics, f"Summary metrics JSON missing required key: '{key}'"
        val = metrics[key]
        assert isinstance(val, (int, float)), f"Metric '{key}' must be numeric, got {type(val)}"
        assert not math.isnan(val) and not math.isinf(val), f"Metric '{key}' is NaN or Inf"

    # Verify NetCDF variables and CF conventions
    ds = nc.Dataset(OUTPUT_NC_PATH, "r")
    try:
        assert hasattr(ds, "Conventions"), "NetCDF missing 'Conventions' global attribute"
        assert "CF-" in str(ds.Conventions), f"NetCDF Conventions attribute must indicate CF compliance, got {ds.Conventions}"

        assert "time" in ds.dimensions, "NetCDF missing 'time' dimension"
        assert "time" in ds.variables, "NetCDF missing 'time' variable"
        assert "discharge" in ds.variables, "NetCDF missing 'discharge' variable"
        assert "cumulative_volume" in ds.variables, "NetCDF missing 'cumulative_volume' variable"

        times = np.array(ds.variables["time"][:])
        discharges = np.array(ds.variables["discharge"][:])
        cum_vols = np.array(ds.variables["cumulative_volume"][:])

        assert len(times) > 0, "NetCDF time series is empty"
        assert len(times) == len(discharges), "Length of 'time' and 'discharge' mismatch"
        assert len(times) == len(cum_vols), "Length of 'time' and 'cumulative_volume' mismatch"

        assert not np.any(np.isnan(discharges)), "Discharge series contains NaN values"
        assert not np.any(np.isinf(discharges)), "Discharge series contains infinite values"
        assert np.all(discharges >= 0.0), "Discharge series contains negative flow rates"
    finally:
        ds.close()


def test_mass_balance_conservation():
    """
    Verifies that the hydrologic simulation strictly conserves mass across all mesh cells
    and that relative mass balance error is below 1e-4% (1e-6 relative tolerance).
    """
    with open(OUTPUT_JSON_PATH, "r") as f:
        metrics = json.load(f)

    mass_err_pct = float(metrics["mass_balance_error_percent"])
    assert mass_err_pct < 1e-4, f"Mass balance error ({mass_err_pct:.6e}%) exceeds required threshold (< 1e-4%)"

    total_vol = float(metrics["total_runoff_volume_m3"])
    assert total_vol > 1000.0, f"Total runoff volume ({total_vol} m3) is unphysically low"

    # Cross-check with NetCDF cumulative volume
    ds = nc.Dataset(OUTPUT_NC_PATH, "r")
    try:
        cum_vol_final = float(ds.variables["cumulative_volume"][-1])
        assert abs(cum_vol_final - total_vol) / total_vol < 1e-3, (
            f"Summary JSON total volume ({total_vol}) does not match NetCDF cumulative volume ({cum_vol_final})"
        )
    finally:
        ds.close()


def test_hydrograph_hydrodynamics_fidelity():
    """
    Verifies hydrodynamic fidelity against calibrated reference gauge data:
    1) Nash-Sutcliffe Efficiency (NSE) >= 0.98
    2) Peak discharge timing matches within 0 timesteps (exact hydrograph peak lag).
    """
    assert os.path.exists(REF_HYDROGRAPH_PATH), f"Reference hydrograph missing at {REF_HYDROGRAPH_PATH}"

    with open(REF_HYDROGRAPH_PATH, "r") as f:
        ref_data = json.load(f)

    ref_q = np.array(ref_data["discharge_m3s"], dtype=np.float64)
    ref_peak_time_idx = int(np.argmax(ref_q))

    ds = nc.Dataset(OUTPUT_NC_PATH, "r")
    try:
        sim_q = np.array(ds.variables["discharge"][:], dtype=np.float64)
    finally:
        ds.close()

    assert len(sim_q) == len(ref_q), f"Simulation duration ({len(sim_q)}) does not match reference ({len(ref_q)})"

    # Compute exact NSE
    mean_ref = np.mean(ref_q)
    numerator = np.sum((ref_q - sim_q) ** 2)
    denominator = np.sum((ref_q - mean_ref) ** 2)
    nse = float(1.0 - (numerator / denominator))

    assert nse >= 0.98, f"Hydrograph Nash-Sutcliffe Efficiency ({nse:.4f}) is below acceptable threshold (>= 0.98)"

    # Verify peak timing
    sim_peak_time_idx = int(np.argmax(sim_q))
    timing_diff = abs(sim_peak_time_idx - ref_peak_time_idx)
    assert timing_diff == 0, (
        f"Peak discharge timing lag mismatch: simulated peak at step {sim_peak_time_idx}, "
        f"expected reference peak at step {ref_peak_time_idx} (diff={timing_diff})"
    )


def test_holdout_extreme_storm_generalization():
    """
    Anti-cheat & Metamorphic Test:
    Re-runs the compiled Rust solver and Python framework on an unseen held-out extreme storm event.
    Verifies that the conservative flux limiter operates stably under extreme precipitation rates
    without numerical divergence, NaN states, or mass balance leaks.
    """
    assert os.path.exists(SOLVER_BIN_PATH), f"Compiled solver binary not found at {SOLVER_BIN_PATH}"

    if not os.path.exists(HOLDOUT_FORCING_NC):
        pytest.skip(f"Holdout forcing NetCDF {HOLDOUT_FORCING_NC} not present")

    temp_out_nc = "/tmp/holdout_discharge.nc"
    temp_out_json = "/tmp/holdout_metrics.json"

    # Run the simulation on holdout forcing
    cmd = [
        "python3", "/app/run_simulation.py",
        "--config", BASIN_CONFIG_PATH,
        "--mesh", MESH_JSON_PATH,
        "--forcing", HOLDOUT_FORCING_NC,
        "--output-nc", temp_out_nc,
        "--output-json", temp_out_json,
        "--solver", SOLVER_BIN_PATH,
    ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert res.returncode == 0, f"Simulation failed on holdout extreme storm: {res.stderr}\n{res.stdout}"

    assert os.path.exists(temp_out_json), "Holdout simulation metrics JSON was not created"
    with open(temp_out_json, "r") as f:
        holdout_metrics = json.load(f)

    mass_err_pct = float(holdout_metrics["mass_balance_error_percent"])
    assert mass_err_pct < 1e-4, f"Holdout mass balance error ({mass_err_pct:.6e}%) exceeds required threshold (< 1e-4%)"

    peak_q = float(holdout_metrics["peak_discharge_m3s"])
    assert peak_q > 5.0, f"Holdout peak discharge ({peak_q} m3/s) unexpectedly low for extreme storm"
