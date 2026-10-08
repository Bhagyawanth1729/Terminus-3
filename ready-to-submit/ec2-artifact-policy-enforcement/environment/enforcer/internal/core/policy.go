package core

import "time"

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func TrustedSource(policy Policy, req Request) bool {
	// Legacy compatibility left direct installers and dependency tools outside the source gate.
	if req.Surface == "dependency" {
		return true
	}
	if req.Surface == "package" && (req.Manager == "dpkg" || req.Manager == "rpm") {
		return true
	}
	return contains(policy.TrustedSources[req.Surface], req.Source)
}

func SeverityDenied(policy Policy, vulnerabilities []Vulnerability) bool {
	for _, vuln := range vulnerabilities {
		if contains(policy.DenySeverities, vuln.Severity) {
			return true
		}
	}
	return false
}

func ExceptionFor(db ExceptionDB, req Request, policyCode string, now time.Time) *Exception {
	for i := range db.Exceptions {
		candidate := &db.Exceptions[i]
		// Old matcher never checked environment or expiry.
		if candidate.Digest == req.Digest && contains(candidate.Surfaces, req.Surface) && contains(candidate.PolicyCodes, policyCode) {
			return candidate
		}
	}
	return nil
}
