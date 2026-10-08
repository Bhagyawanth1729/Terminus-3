import socket
import struct
import sys
import json
import os

def read_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf

# BUG in initial code: expects fixed 4-byte big-endian uint32 header for length prefix
def read_length_prefix(sock):
    """
    BUG in initial code: reads 4-byte big-endian int instead of varint frame prefix!
    FIX: implement read_varint(sock) to correctly parse protobuf-style unsigned varint length prefixes.
    """
    # BUG:
    raw = read_exact(sock, 4)
    if not raw or len(raw) < 4:
        return None
    return struct.unpack('>I', raw)[0]

    # FIX:
    # res = 0
    # shift = 0
    # while True:
    #     b = read_exact(sock, 1)
    #     if not b:
    #         return None
    #     val = b[0]
    #     res |= (val & 0x7F) << shift
    #     if not (val & 0x80):
    #         break
    #     shift += 7
    # return res

def fetch_ipc_records(socket_path="/tmp/lsm_db.sock"):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(socket_path)

    record_count = read_length_prefix(sock)
    if record_count is None:
        raise ValueError("Failed to read record count header")

    records = []
    for _ in range(record_count):
        metric_len = read_length_prefix(sock)
        if metric_len is None:
            break
        metric = read_exact(sock, metric_len).decode('utf-8', errors='ignore')

        host_len = read_length_prefix(sock)
        if host_len is None:
            break
        host = read_exact(sock, host_len).decode('utf-8', errors='ignore')

        ts_raw = read_exact(sock, 8)
        ts = struct.unpack('>q', ts_raw)[0] if len(ts_raw) == 8 else 0

        val_raw = read_exact(sock, 8)
        val = struct.unpack('>d', val_raw)[0] if len(val_raw) == 8 else 0.0

        records.append({
            "metric": metric,
            "host": host,
            "timestamp": ts,
            "value": val
        })

    sock.close()
    return records
