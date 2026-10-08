mod flux;
mod ipc;
mod mesh;
mod types;

use flux::compute_step;
use ipc::BinaryIpc;
use mesh::TriangularMesh;
use std::env;
use std::io::{self, BufReader, BufWriter};
use std::process;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: rust_solver <mesh_tin.json>");
        process::exit(1);
    }

    let mesh_path = &args[1];
    let mut mesh = match TriangularMesh::load_from_json(mesh_path) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("Error loading mesh JSON from {}: {}", mesh_path, e);
            process::exit(1);
        }
    };

    let stdin = io::stdin();
    let mut stdin_reader = BufReader::new(stdin.lock());

    let stdout = io::stdout();
    let mut stdout_writer = BufWriter::new(stdout.lock());

    // 1. Read initial cell states from binary stream
    let cell_states = match BinaryIpc::read_cell_states(&mut stdin_reader) {
        Ok(states) => states,
        Err(e) => {
            eprintln!("Error reading initial cell states over IPC: {}", e);
            process::exit(1);
        }
    };

    if cell_states.len() != mesh.cells.len() {
        eprintln!(
            "Mismatch in cell count: IPC provided {} cells, mesh has {}",
            cell_states.len(),
            mesh.cells.len()
        );
        process::exit(1);
    }

    for (i, state) in cell_states.into_iter().enumerate() {
        mesh.cells[i].state = state;
    }

    // 2. Step through simulation forcing packets
    let mut step_index = 0;
    loop {
        match BinaryIpc::read_step_forcing(&mut stdin_reader) {
            Ok(Some(forcing)) => {
                let res = compute_step(&mut mesh, &forcing, step_index);
                if let Err(e) = BinaryIpc::write_step_result(&mut stdout_writer, &res) {
                    eprintln!("Error writing step result {}: {}", step_index, e);
                    process::exit(1);
                }
                step_index += 1;
            }
            Ok(None) => break, // EOF reached cleanly
            Err(e) => {
                eprintln!("Error reading forcing packet {}: {}", step_index, e);
                process::exit(1);
            }
        }
    }
}
