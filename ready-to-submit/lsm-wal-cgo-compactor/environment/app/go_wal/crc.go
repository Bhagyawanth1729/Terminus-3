package main

import (
	"hash/crc32"
)

// CastagnoliTable is the hardware-accelerated CRC32c polynomial table (0x82F63B78).
var CastagnoliTable = crc32.MakeTable(crc32.Castagnoli)

// IEEE Table (0xEDB88320) - used erroneously in initial code!
var IEEETable = crc32.IEEETable

func ComputeCRC32c(data []byte) uint32 {
	// BUG in initial code: uses IEEETable instead of CastagnoliTable
	return crc32.Checksum(data, IEEETable)
	// FIX: return crc32.Checksum(data, CastagnoliTable)
}
