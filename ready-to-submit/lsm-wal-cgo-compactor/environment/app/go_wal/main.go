package main

import (
	"encoding/binary"
	"fmt"
	"log"
	"net"
	"os"
	"path/filepath"
	"sort"
)

func writeVarint(buf []byte, x uint64) int {
	i := 0
	for x >= 0x80 {
		buf[i] = byte(x | 0x80)
		x >>= 7
		i++
	}
	buf[i] = byte(x)
	return i + 1
}

func main() {
	if len(os.Args) > 1 && os.Args[1] == "--help" {
		fmt.Println("Go WAL Compactor Service")
		return
	}

	dataDir := "/app/data"
	if envDataDir := os.Getenv("WAL_DATA_DIR"); envDataDir != "" {
		dataDir = envDataDir
	}

	sstDir := "/app/sst"
	if envSstDir := os.Getenv("SST_OUTPUT_DIR"); envSstDir != "" {
		sstDir = envSstDir
	}

	if err := os.MkdirAll(sstDir, 0755); err != nil {
		log.Fatalf("Failed to create sst dir: %v", err)
	}

	files, err := filepath.Glob(filepath.Join(dataDir, "*.wal"))
	if err != nil {
		log.Fatalf("Failed to list wal files: %v", err)
	}
	sort.Strings(files)

	var allRecords []Record

	for idx, f := range files {
		recs, rawData, err := ReadWALFile(f)
		if err != nil {
			log.Fatalf("Error reading %s: %v", f, err)
		}
		allRecords = append(allRecords, recs...)

		sstPath := filepath.Join(sstDir, fmt.Sprintf("shard_%03d.sst", idx+1))
		crc, err := CompactWALViaRust(sstPath, rawData)
		if err != nil {
			log.Fatalf("Compaction failed for %s: %v", f, err)
		}
		log.Printf("Compacted %s -> %s (CRC: %08x)", f, sstPath, crc)
	}

	socketPath := "/tmp/lsm_db.sock"
	os.Remove(socketPath)

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		log.Fatalf("Failed to listen on unix socket: %v", err)
	}
	defer listener.Close()

	log.Printf("IPC Server listening on %s, total records: %d", socketPath, len(allRecords))

	// Listen for 1 IPC request and respond with records, then exit
	conn, err := listener.Accept()
	if err != nil {
		log.Fatalf("Accept error: %v", err)
	}
	defer conn.Close()

	// Send record count as varint
	var varbuf [10]byte
	n := writeVarint(varbuf[:], uint64(len(allRecords)))
	conn.Write(varbuf[:n])

	for _, r := range allRecords {
		// Send metric string (varint len + bytes)
		mb := []byte(r.Metric)
		n = writeVarint(varbuf[:], uint64(len(mb)))
		conn.Write(varbuf[:n])
		conn.Write(mb)

		// Send host string (varint len + bytes)
		hb := []byte(r.Host)
		n = writeVarint(varbuf[:], uint64(len(hb)))
		conn.Write(varbuf[:n])
		conn.Write(hb)

		// Send ts (8 bytes)
		var b8 [8]byte
		binary.BigEndian.PutUint64(b8[:], uint64(r.Ts))
		conn.Write(b8[:])

		// Send val (8 bytes)
		binary.BigEndian.PutUint64(b8[:], uint64(r.Val))
		conn.Write(b8[:])
	}

	log.Printf("IPC transaction completed successfully")
}
