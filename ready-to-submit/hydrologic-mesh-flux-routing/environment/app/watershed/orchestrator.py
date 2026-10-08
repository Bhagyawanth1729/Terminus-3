import os
import subprocess
import struct
import numpy as np
from typing import List, Dict, Any, Tuple
from watershed.mesh import WatershedMesh
from watershed.forcing import MeteorologicalForcing


class SimulationOrchestrator:
    def __init__(self, solver_bin: str, mesh: WatershedMesh, forcing: MeteorologicalForcing):
        self.solver_bin = solver_bin
        self.mesh = mesh
        self.forcing = forcing
        self.config = mesh.config

    def run(self) -> Dict[str, Any]:
        """
        Executes the Rust numerical solver subprocess over binary stdin/stdout IPC.
        Streams initial cell states followed by per-timestep meteorological forcing packets.
        Collects hydrodynamic discharge results.
        """
        if not os.path.exists(self.solver_bin):
            raise FileNotFoundError(f"Rust solver binary not found at {self.solver_bin}. Did you run build.sh?")

        mesh_json_path = os.path.join(os.path.dirname(self.mesh.config.get("mesh_file", "data/mesh_tin.json")), "mesh_tin.json")
        if not os.path.isabs(mesh_json_path):
            mesh_json_path = os.path.abspath(mesh_json_path)

        proc = subprocess.Popen(
            [self.solver_bin, mesh_json_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        # 1. Send initial packed binary cell states
        packed_states = self.mesh.pack_binary_cell_states()
        proc.stdin.write(packed_states)
        proc.stdin.flush()

        results = []
        raw_discharges = []
        storage_vols = []
        inflow_vols = []
        outflow_vols = []

        # 2. Stream forcing packets and read step results
        for step in range(self.forcing.num_timesteps):
            dt, p_arr, inf_arr = self.forcing.get_step_forcing(step)

            # Format: [dt: f64], [cell_count: u32], [precip: f64 * count], [infil: f64 * count]
            packet = bytearray()
            packet.extend(struct.pack("<dI", float(dt), self.mesh.num_cells))
            packet.extend(p_arr.astype("<f8").tobytes())
            packet.extend(inf_arr.astype("<f8").tobytes())

            proc.stdin.write(packet)
            proc.stdin.flush()

            # Read result packet: [step_index: u64], [q: f64], [storage: f64], [inflow: f64], [outflow: f64], [max_h: f64], [min_h: f64]
            # 8 + 8*6 = 56 bytes
            result_bytes = proc.stdout.read(56)
            if len(result_bytes) < 56:
                stderr_out = proc.stderr.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Rust solver terminated prematurely at step {step}: {stderr_out}")

            step_idx, q_out, storage, in_vol, out_vol, max_h, min_h = struct.unpack("<Qdddddd", result_bytes)
            raw_discharges.append(q_out)
            storage_vols.append(storage)
            inflow_vols.append(in_vol)
            outflow_vols.append(out_vol)

        # Close stdin to signal EOF to Rust solver
        proc.stdin.close()
        proc.wait(timeout=10)

        # 3. Apply downstream main channel routing delay
        channel_lag_sec = float(self.config.get("channel_routing", {}).get("reach_lag_seconds", 30.0))
        dt = self.forcing.dt

        # BROKEN: Timestep delta scaling factor error in channel lag calculation
        # It was divided by 1000.0 (erroneously converting seconds to milliseconds ratio)
        lag_steps = int(channel_lag_sec / (dt / 1000.0))

        routed_discharges = np.zeros(len(raw_discharges), dtype=np.float64)
        if lag_steps > 0 and lag_steps < len(raw_discharges):
            routed_discharges[lag_steps:] = raw_discharges[:-lag_steps]
        else:
            routed_discharges = np.array(raw_discharges, dtype=np.float64)

        return {
            "time_seconds": self.forcing.time,
            "raw_discharge": np.array(raw_discharges, dtype=np.float64),
            "discharge": routed_discharges,
            "storage_volumes": np.array(storage_vols, dtype=np.float64),
            "inflow_volumes": np.array(inflow_vols, dtype=np.float64),
            "outflow_volumes": np.array(outflow_vols, dtype=np.float64),
        }
