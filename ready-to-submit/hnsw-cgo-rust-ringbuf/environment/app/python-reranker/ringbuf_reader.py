import mmap
import os
import struct
import time

MAGIC_HNSW = 0x484E5357

class RingBufferReader:
    def __init__(self, file_path="/tmp/hnsw_ring.buf", capacity=2048):
        self.file_path = file_path
        self.capacity = capacity
        self.header_size = 32
        self.item_size = 128
        self.mm = None
        self.file_obj = None

    def open(self):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Ring buffer file not found: {self.file_path}")

        self.file_obj = open(self.file_path, "r+b")
        self.mm = mmap.mmap(self.file_obj.fileno(), 0)

        magic, cap, item_sz = struct.unpack("<III", self.mm[0:12])
        if magic != MAGIC_HNSW:
            raise ValueError(f"Invalid magic number: {hex(magic)}, expected {hex(MAGIC_HNSW)}")
        self.capacity = cap
        self.item_size = item_sz

    def get_heads(self):
        # write_head is at offset 12, read_head is at offset 16
        write_head, read_head = struct.unpack("<II", self.mm[12:20])
        return write_head, read_head

    def read_items(self, max_items=10000):
        write_head, read_head = self.get_heads()
        items = []
        
        # Read available slots up to write_head
        for idx in range(write_head):
            slot_idx = idx % self.capacity
            slot_offset = self.header_size + slot_idx * self.item_size
            
            slot_data = self.mm[slot_offset : slot_offset + self.item_size]
            query_id, node_id, distance, vec_dim = struct.unpack("<IQfI", slot_data[0:20])
            
            if vec_dim > 0 and vec_dim <= 16:
                vec_data = struct.unpack(f"<{vec_dim}f", slot_data[20 : 20 + vec_dim * 4])
            else:
                vec_data = ()

            items.append({
                "slot_idx": idx,
                "query_id": query_id,
                "node_id": node_id,
                "distance": distance,
                "vector_dim": vec_dim,
                "vector": list(vec_data)
            })

        return items

    def close(self):
        if self.mm:
            self.mm.close()
        if self.file_obj:
            self.file_obj.close()
