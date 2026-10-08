import os
import mmap
import struct
import time
import urllib.request
import json

SHM_PATH = "/dev/shm/tensor_ringbuf.shm"
RINGBUF_CAPACITY = 64
SLOT_HEADER_SIZE = 32
HEADER_SIZE = 16 + (RINGBUF_CAPACITY * SLOT_HEADER_SIZE)

SLOT_STATE_EMPTY = 0
SLOT_STATE_WRITING = 1
SLOT_STATE_READY = 2
SLOT_STATE_PROCESSING = 3
SLOT_STATE_COMPLETED = 4
SLOT_STATE_CANCELLED = 5

class BatchOrchestrator:
    def __init__(self, shm_path=SHM_PATH):
        self.shm_path = shm_path
        self.active_requests = {}
        self.shm_file = None
        self.mm = None

    def open_shm(self):
        if not os.path.exists(self.shm_path):
            return False
        total_size = HEADER_SIZE + (RINGBUF_CAPACITY * 4096) + 4096
        self.shm_file = open(self.shm_path, "r+b")
        self.mm = mmap.mmap(self.shm_file.fileno(), total_size)
        return True

    def close(self):
        if self.mm:
            self.mm.close()
        if self.shm_file:
            self.shm_file.close()

    def get_slot_state(self, slot_idx):
        if not self.mm:
            return None
        offset = 16 + (slot_idx * SLOT_HEADER_SIZE)
        slot_id, state, num_elements, scale_bits, data_offset = struct.unpack_from("<IIIII", self.mm, offset)
        return state

    def set_slot_state(self, slot_idx, state):
        if not self.mm:
            return
        offset = 16 + (slot_idx * SLOT_HEADER_SIZE) + 4
        struct.pack_into("<I", self.mm, offset, state)

    # BUG 3 (Original): Drops tracked request from local map without resetting slot state
    # or advancing tail in the shared memory header, causing ring buffer capacity leaks.
    def clean_expired_requests(self, timeout_sec=2.0):
        now = time.time()
        expired = []
        for req_id, (slot_idx, start_time) in list(self.active_requests.items()):
            if now - start_time > timeout_sec:
                expired.append(req_id)
                # BUG: Does NOT reset slot state in shared memory or update tail pointer!
                # It just deletes from local dictionary:
                del self.active_requests[req_id]
        return expired

    def track_request(self, req_id, slot_idx):
        self.active_requests[req_id] = (slot_idx, time.time())

if __name__ == "__main__":
    orch = BatchOrchestrator()
    if orch.open_shm():
        print("BatchOrchestrator connected to shared memory.")
    else:
        print("Waiting for shared memory creation...")
