package platform

func Scan(scans ScanDB, digest string) ScanRecord {
	if record, ok := scans.Records[digest]; ok {
		return record
	}
	return ScanRecord{Status: "unavailable"}
}

func ScannerHealthy(record ScanRecord) bool {
	return record.Status == "ok"
}

func ScannerRevisionMatches(policy Policy, record ScanRecord) bool {
	return record.DBRevision == policy.ScannerDBRevision
}

func VulnerabilityIDs(record ScanRecord) []string {
	ids := make([]string, 0, len(record.Vulnerabilities))
	for _, vulnerability := range record.Vulnerabilities {
		ids = append(ids, vulnerability.ID)
	}
	return ids
}

func ScannerSummary(record ScanRecord) map[string]interface{} {
	return map[string]interface{}{
		"status":              record.Status,
		"db_revision":         record.DBRevision,
		"max_severity":        maxSeverity(record.Vulnerabilities),
		"vulnerability_count": len(record.Vulnerabilities),
	}
}
