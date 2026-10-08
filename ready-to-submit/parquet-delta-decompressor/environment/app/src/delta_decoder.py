import ctypes
import os
import sys

_lib_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib", "libdeltaparquet.so")

try:
    _lib = ctypes.CDLL(_lib_path)
except Exception as e:
    _lib = None


def is_library_available():
    return _lib is not None


if _lib:
    # BROKEN: Function argument types declare buffer lengths as c_int32 instead of c_uint64!
    # On 64-bit x86 architectures, passing 64-bit buffer lengths as c_int32 causes
    # calling convention argument mismatches or integer overflow on large datasets.
    _lib.decode_delta_stream.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_int32,  # BROKEN: should be ctypes.c_uint64
        ctypes.POINTER(ctypes.c_int64),
        ctypes.c_int32,  # BROKEN: should be ctypes.c_uint64
        ctypes.POINTER(ctypes.c_uint64),
    ]
    _lib.decode_delta_stream.restype = ctypes.c_int32

    _lib.decode_dictionary_stream.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_int32,  # BROKEN: should be ctypes.c_uint64
        ctypes.c_char_p,
        ctypes.c_int32,  # BROKEN: should be ctypes.c_uint64
    ]
    _lib.decode_dictionary_stream.restype = ctypes.c_int32


def decode_timestamps(compressed_bytes: bytes, max_records: int = 100000):
    if not _lib:
        raise RuntimeError(f"Native library not loaded from {_lib_path}")

    c_compressed = (ctypes.c_uint8 * len(compressed_bytes)).from_buffer_copy(compressed_bytes)
    out_buf = (ctypes.c_int64 * max_records)()
    neg_count = ctypes.c_uint64(0)

    res = _lib.decode_delta_stream(
        c_compressed,
        len(compressed_bytes),
        out_buf,
        max_records,
        ctypes.byref(neg_count),
    )

    if res < 0:
        raise ValueError(f"Delta decoding failed with status code {res}")

    timestamps = [out_buf[i] for i in range(res)]
    return timestamps, neg_count.value


def decode_dictionary(dict_bytes: bytes):
    if not _lib:
        raise RuntimeError(f"Native library not loaded from {_lib_path}")

    c_dict = (ctypes.c_uint8 * len(dict_bytes)).from_buffer_copy(dict_bytes)
    max_json = 65536
    json_buf = ctypes.create_string_buffer(max_json)

    res = _lib.decode_dictionary_stream(
        c_dict,
        len(dict_bytes),
        json_buf,
        max_json,
    )

    if res < 0:
        raise ValueError(f"Dictionary decoding failed with status code {res}")

    joined_str = json_buf.value.decode("utf-8")
    return joined_str.split(",") if joined_str else []
