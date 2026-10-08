package platform

import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
	"time"
)

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func parseRFC3339(value string) (time.Time, error) {
	return time.Parse(time.RFC3339, value)
}

func stableID(parts ...string) string {
	sum := sha256.Sum256([]byte(strings.Join(parts, "|")))
	return hex.EncodeToString(sum[:])
}

func normalizeManager(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
}

func normalizeSurface(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
}

func normalizeSource(value string) string {
	return strings.TrimSpace(value)
}

func severityRank(value string) int {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "critical":
		return 5
	case "high":
		return 4
	case "medium":
		return 3
	case "low":
		return 2
	case "negligible":
		return 1
	default:
		return 0
	}
}

func maxSeverity(vulnerabilities []Vulnerability) string {
	result := "unknown"
	rank := 0
	for _, vulnerability := range vulnerabilities {
		current := severityRank(vulnerability.Severity)
		if current > rank {
			rank = current
			result = vulnerability.Severity
		}
	}
	return result
}
