package core

func Scan(scans ScanDB, digest string) ScanRecord {
	if record, ok := scans.Records[digest]; ok {
		return record
	}
	return ScanRecord{Status: "unavailable"}
}
