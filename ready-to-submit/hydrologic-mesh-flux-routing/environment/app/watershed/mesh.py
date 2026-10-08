import json
import struct
from typing import Dict, List, Any


class WatershedMesh:
    def __init__(self, config_path: str, mesh_path: str):
        with open(config_path, "r") as f:
            self.config = json.load(f)
        with open(mesh_path, "r") as f:
            self.mesh_data = json.load(f)

        self.cells = self.mesh_data["cells"]
        self.outlet_ids = self.mesh_data["outlet_ids"]
        self.num_cells = len(self.cells)

    def pack_binary_cell_states(self) -> bytes:
        """
        Packs cell states into a contiguous C-struct binary buffer for IPC transfer.
        C-ABI struct layout expected by numerical kernel:
        struct CellState {
            double elevation;
            double area;
            double manning_n;
            double slope;
            double water_depth;
            uint32_t flags;
            uint32_t pad;
        };
        """
        buffer = bytearray()
        # Write cell count (u32)
        buffer.extend(struct.pack("<I", self.num_cells))

        for cell in self.cells:
            state = cell["state"]
            # NOTE: Packing cell state attributes into binary buffer
            # Format: <dddddII
            packed = struct.pack(
                "<dddddII",
                float(state["elevation"]),
                float(state["area"]),
                float(state["slope"]),     # BROKEN: slope packed before manning_n
                float(state["manning_n"]), # BROKEN: manning_n packed after slope
                float(state["water_depth"]),
                int(state.get("flags", 0)),
                int(state.get("pad", 0)),
            )
            buffer.extend(packed)

        return bytes(buffer)
