use std::collections::HashMap;
use std::env;
use std::fs;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

const HEADER_SIZE: usize = 20;
const END_MAGIC: u32 = 0x324B_5043;
const HAS_DICT: u8 = 0x01;

#[derive(Clone, Debug, PartialEq, Eq)]
struct ColumnSpec {
    name: String,
    col_type: u8,
}

#[derive(Clone, Debug)]
struct ParsedCpk {
    dictionary: Vec<String>,
    columns: Vec<ColumnSpec>,
    payloads: Vec<Vec<u8>>,
    row_count: u32,
}

fn read_exact_at(data: &[u8], offset: usize, len: usize) -> io::Result<&[u8]> {
    data.get(offset..offset + len)
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "out of range read"))
}

fn parse_cpk(path: &Path) -> io::Result<ParsedCpk> {
    let data = fs::read(path)?;
    if data.len() < HEADER_SIZE + 8 || &data[0..4] != b"CPK2" {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "bad cpk header"));
    }
    let version = data[4];
    if version != 2 {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "unsupported version"));
    }
    let flags = data[5];
    let column_count = u32::from_le_bytes(data[6..10].try_into().unwrap()) as usize;
    let row_count = u32::from_le_bytes(data[10..14].try_into().unwrap());
    let body_length = u32::from_le_bytes(data[14..18].try_into().unwrap()) as usize;
    let body_start = HEADER_SIZE;
    let body = read_exact_at(&data, body_start, body_length)?;

    let expected_crc = u32::from_le_bytes(data[body_start + body_length..body_start + body_length + 4].try_into().unwrap());
    let tail = u32::from_le_bytes(data[body_start + body_length + 4..body_start + body_length + 8].try_into().unwrap());
    if tail != END_MAGIC {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "bad footer magic"));
    }
    let actual_crc = crc32fast(&data[..body_start + body_length]);
    if actual_crc != expected_crc {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "crc mismatch"));
    }

    let mut offset = 0usize;
    let mut dictionary = Vec::new();
    if flags & HAS_DICT != 0 {
        let dict_count = u32::from_le_bytes(body[offset..offset + 4].try_into().unwrap()) as usize;
        offset += 4;
        for _ in 0..dict_count {
            let entry_len = u16::from_le_bytes(body[offset..offset + 2].try_into().unwrap()) as usize;
            offset += 2;
            let entry = std::str::from_utf8(&body[offset..offset + entry_len])
                .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "bad utf8"))?
                .to_string();
            offset += entry_len;
            dictionary.push(entry);
        }
    }

    let mut columns = Vec::with_capacity(column_count);
    let mut payload_specs = Vec::with_capacity(column_count);
    for _ in 0..column_count {
        let name_len = u16::from_le_bytes(body[offset..offset + 2].try_into().unwrap()) as usize;
        offset += 2;
        let name = std::str::from_utf8(&body[offset..offset + name_len])
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "bad column name"))?
            .to_string();
        offset += name_len;
        let col_type = body[offset];
        offset += 1;
        let data_offset = u32::from_le_bytes(body[offset..offset + 4].try_into().unwrap()) as usize;
        offset += 4;
        let data_length = u32::from_le_bytes(body[offset..offset + 4].try_into().unwrap()) as usize;
        offset += 4;
        columns.push(ColumnSpec { name, col_type });
        payload_specs.push((data_offset, data_length));
    }

    let mut payloads = Vec::with_capacity(column_count);
    for (data_offset, data_length) in payload_specs {
        let abs = body_start + data_offset;
        let slice = read_exact_at(&data, abs, data_length)?;
        payloads.push(slice.to_vec());
    }

    Ok(ParsedCpk {
        dictionary,
        columns,
        payloads,
        row_count,
    })
}

fn crc32fast(data: &[u8]) -> u32 {
    let mut crc = 0xFFFF_FFFFu32;
    for byte in data {
        crc ^= u32::from(*byte);
        for _ in 0..8 {
            if crc & 1 != 0 {
                crc = (crc >> 1) ^ 0xEDB8_8320;
            } else {
                crc >>= 1;
            }
        }
    }
    !crc
}

fn merge_inputs(inputs: &[ParsedCpk]) -> io::Result<ParsedCpk> {
    if inputs.is_empty() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "no inputs"));
    }
    let schema = inputs[0].columns.clone();
    for item in inputs.iter().skip(1) {
        if item.columns != schema {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "schema mismatch"));
        }
    }

    let mut merged_dict: Vec<String> = Vec::new();
    let mut dict_map: HashMap<String, u32> = HashMap::new();
    for item in inputs {
        for entry in &item.dictionary {
            if !dict_map.contains_key(entry) {
                dict_map.insert(entry.clone(), merged_dict.len() as u32);
                merged_dict.push(entry.clone());
            }
        }
    }

    let mut merged_payloads: Vec<Vec<u8>> = vec![Vec::new(); schema.len()];
    let mut merged_rows = 0u32;

    for item in inputs {
        merged_rows += item.row_count;
        for (idx, col) in schema.iter().enumerate() {
            let chunk = &item.payloads[idx];
            match col.col_type {
                0 | 2 => merged_payloads[idx].extend_from_slice(chunk),
                1 => {
                    let rows = item.row_count as usize;
                    for row_idx in 0..rows {
                        let start = row_idx * 4;
                        let old_idx = u32::from_le_bytes(chunk[start..start + 4].try_into().unwrap()) as usize;
                        let value = item
                            .dictionary
                            .get(old_idx)
                            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "bad dict idx"))?;
                        let new_idx = dict_map[value];
                        merged_payloads[idx].extend_from_slice(&new_idx.to_le_bytes());
                    }
                }
                _ => return Err(io::Error::new(io::ErrorKind::InvalidData, "unknown col type")),
            }
        }
    }

    Ok(ParsedCpk {
        dictionary: merged_dict,
        columns: schema,
        payloads: merged_payloads,
        row_count: merged_rows,
    })
}

fn write_cpk(path: &Path, parsed: &ParsedCpk) -> io::Result<()> {
    let mut dict_bytes = Vec::new();
    if !parsed.dictionary.is_empty() {
        dict_bytes.extend_from_slice(&(parsed.dictionary.len() as u32).to_le_bytes());
        for entry in &parsed.dictionary {
            let raw = entry.as_bytes();
            dict_bytes.extend_from_slice(&(raw.len() as u16).to_le_bytes());
            dict_bytes.extend_from_slice(raw);
        }
    }

    let mut directory = Vec::new();
    let mut data_blob = Vec::new();
    let mut cursor = dict_bytes.len() as u32;
    for (col, payload) in parsed.columns.iter().zip(parsed.payloads.iter()) {
        let name_raw = col.name.as_bytes();
        directory.extend_from_slice(&(name_raw.len() as u16).to_le_bytes());
        directory.extend_from_slice(name_raw);
        directory.push(col.col_type);
        directory.extend_from_slice(&cursor.to_le_bytes());
        directory.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        data_blob.extend_from_slice(payload);
        cursor += payload.len() as u32;
    }

    let body: Vec<u8> = dict_bytes
        .into_iter()
        .chain(directory)
        .chain(data_blob)
        .collect();
    let flags = if parsed.dictionary.is_empty() { 0 } else { HAS_DICT };
    let mut header = Vec::with_capacity(HEADER_SIZE);
    header.extend_from_slice(b"CPK2");
    header.push(2);
    header.push(flags);
    header.extend_from_slice(&(parsed.columns.len() as u32).to_le_bytes());
    header.extend_from_slice(&parsed.row_count.to_le_bytes());
    header.extend_from_slice(&(body.len() as u32).to_le_bytes());

    let mut file = Vec::new();
    file.extend_from_slice(&header);
    file.extend_from_slice(&body);
    let crc = crc32fast(&file);
    file.extend_from_slice(&crc.to_le_bytes());
    file.extend_from_slice(&END_MAGIC.to_le_bytes());

    fs::write(path, file)
}

fn main() -> io::Result<()> {
    let mut args = env::args().skip(1);
    let cmd = args.next().ok_or_else(|| usage())?;
    if cmd != "merge" {
        return Err(usage());
    }

    let mut inputs: Vec<PathBuf> = Vec::new();
    let mut output: Option<PathBuf> = None;
    while let Some(flag) = args.next() {
        match flag.as_str() {
            "--input" => inputs.push(PathBuf::from(args.next().ok_or_else(|| usage())?)),
            "--output" => output = Some(PathBuf::from(args.next().ok_or_else(|| usage())?)),
            _ => return Err(usage()),
        }
    }
    let output = output.ok_or_else(|| usage())?;
    let parsed: Vec<ParsedCpk> = inputs.iter().map(parse_cpk).collect::<io::Result<_>>()?;
    let merged = merge_inputs(&parsed)?;
    write_cpk(&output, &merged)
}

fn usage() -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidInput,
        "usage: colpack merge --output <path> --input <cpk> [--input <cpk> ...]",
    )
}
