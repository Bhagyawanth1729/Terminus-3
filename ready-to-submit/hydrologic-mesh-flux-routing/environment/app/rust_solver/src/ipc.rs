use crate::types::{CellState, StepForcing, StepResult};
use byteorder::{LittleEndian, ReadBytesExt, WriteBytesExt};
use std::io::{self, Read, Write};

pub struct BinaryIpc;

impl BinaryIpc {
    /// Reads binary cell states buffer:
    /// Format: [cell_count: u32] followed by cell_count * sizeof(CellState)
    /// CellState in Rust memory layout:
    /// elevation (f64), area (f64), manning_n (f64), slope (f64), water_depth (f64), flags (u32), pad (u32)
    pub fn read_cell_states<R: Read>(reader: &mut R) -> io::Result<Vec<CellState>> {
        let count = reader.read_u32::<LittleEndian>()? as usize;
        let mut states = Vec::with_capacity(count);

        for _ in 0..count {
            let elevation = reader.read_f64::<LittleEndian>()?;
            let area = reader.read_f64::<LittleEndian>()?;
            let manning_n = reader.read_f64::<LittleEndian>()?;
            let slope = reader.read_f64::<LittleEndian>()?;
            let water_depth = reader.read_f64::<LittleEndian>()?;
            let flags = reader.read_u32::<LittleEndian>()?;
            let pad = reader.read_u32::<LittleEndian>()?;

            states.push(CellState {
                elevation,
                area,
                manning_n,
                slope,
                water_depth,
                flags,
                pad,
            });
        }
        Ok(states)
    }

    /// Reads a binary forcing packet for one timestep:
    /// Format: [dt_seconds: f64], [cell_count: u32], [precip * cell_count: f64], [infil * cell_count: f64]
    pub fn read_step_forcing<R: Read>(reader: &mut R) -> io::Result<Option<StepForcing>> {
        let dt = match reader.read_f64::<LittleEndian>() {
            Ok(val) => val,
            Err(ref e) if e.kind() == io::ErrorKind::UnexpectedEof => return Ok(None),
            Err(e) => return Err(e),
        };

        let cell_count = reader.read_u32::<LittleEndian>()? as usize;
        let mut precip = Vec::with_capacity(cell_count);
        for _ in 0..cell_count {
            precip.push(reader.read_f64::<LittleEndian>()?);
        }

        let mut infil = Vec::with_capacity(cell_count);
        for _ in 0..cell_count {
            infil.push(reader.read_f64::<LittleEndian>()?);
        }

        Ok(Some(StepForcing {
            precipitation_m_per_s: precip,
            infiltration_m_per_s: infil,
            dt_seconds: dt,
        }))
    }

    /// Writes step result packet:
    /// [step_index: u64], [outlet_q: f64], [storage: f64], [inflow: f64], [outflow: f64], [max_h: f64], [min_h: f64]
    pub fn write_step_result<W: Write>(writer: &mut W, res: &StepResult) -> io::Result<()> {
        writer.write_u64::<LittleEndian>(res.step_index as u64)?;
        writer.write_f64::<LittleEndian>(res.outlet_discharge_m3s)?;
        writer.write_f64::<LittleEndian>(res.total_storage_volume_m3)?;
        writer.write_f64::<LittleEndian>(res.net_inflow_volume_m3)?;
        writer.write_f64::<LittleEndian>(res.net_outflow_volume_m3)?;
        writer.write_f64::<LittleEndian>(res.max_water_depth_m)?;
        writer.write_f64::<LittleEndian>(res.min_water_depth_m)?;
        writer.flush()?;
        Ok(())
    }
}
