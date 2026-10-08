import numpy as np
import netCDF4 as nc
from typing import Dict, List, Tuple


class MeteorologicalForcing:
    def __init__(self, netcdf_path: str, num_cells: int):
        self.netcdf_path = netcdf_path
        self.num_cells = num_cells
        self.ds = nc.Dataset(netcdf_path, "r")
        self.time = np.array(self.ds.variables["time"][:], dtype=np.float64)
        self.dt = float(self.time[1] - self.time[0]) if len(self.time) > 1 else 10.0
        self.num_timesteps = len(self.time)

        # Precipitation: shape (time, cells) in m/s
        if "precipitation" in self.ds.variables:
            self.precip = np.array(self.ds.variables["precipitation"][:], dtype=np.float64)
            if self.precip.ndim == 1:
                # Broadcast across all cells
                self.precip = np.tile(self.precip[:, np.newaxis], (1, self.num_cells))
        else:
            self.precip = np.zeros((self.num_timesteps, self.num_cells), dtype=np.float64)

        # Infiltration: shape (time, cells) in m/s
        if "infiltration" in self.ds.variables:
            self.infil = np.array(self.ds.variables["infiltration"][:], dtype=np.float64)
            if self.infil.ndim == 1:
                self.infil = np.tile(self.infil[:, np.newaxis], (1, self.num_cells))
        else:
            self.infil = np.zeros((self.num_timesteps, self.num_cells), dtype=np.float64)

    def get_step_forcing(self, step_idx: int) -> Tuple[float, np.ndarray, np.ndarray]:
        p = self.precip[step_idx]
        inf = self.infil[step_idx]
        return self.dt, p, inf

    def close(self):
        if self.ds is not None:
            self.ds.close()
            self.ds = None
