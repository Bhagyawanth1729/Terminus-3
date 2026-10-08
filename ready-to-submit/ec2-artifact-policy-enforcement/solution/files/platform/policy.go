package platform

import "strings"

func TrustedSource(policy Policy, req Request) bool {
	req = NormalizeRequest(req)
	for _, source := range policy.TrustedSources[req.Surface] {
		if strings.TrimSpace(source) == req.Source {
			return true
		}
	}
	return false
}

func SeverityDenied(policy Policy, vulnerabilities []Vulnerability) bool {
	for _, vulnerability := range vulnerabilities {
		for _, denied := range policy.DenySeverities {
			if strings.EqualFold(strings.TrimSpace(denied), strings.TrimSpace(vulnerability.Severity)) {
				return true
			}
		}
	}
	return false
}

func MissingRequiredDigest(policy Policy, req Request) bool {
	req = NormalizeRequest(req)
	return policy.RequireDigest[req.Surface] && req.Digest == ""
}

func PolicySnapshotID(policy Policy) string {
	return stableID(policy.Version, policy.ScannerDBRevision)
}

func PolicyViolations(policy Policy, req Request) []PolicyViolation {
	req = NormalizeRequest(req)
	violations := InspectRequest(req)
	if MissingRequiredDigest(policy, req) {
		violations = append(violations, PolicyViolation{Code: "DENY_MISSING_DIGEST", Message: "immutable artifact digest is required", Blocking: true})
	}
	if !TrustedSource(policy, req) {
		violations = append(violations, PolicyViolation{Code: "DENY_UNTRUSTED_SOURCE", Message: "artifact source is not trusted", Blocking: true})
	}
	return violations
}

func HasBlockingViolation(violations []PolicyViolation) bool {
	for _, violation := range violations {
		if violation.Blocking {
			return true
		}
	}
	return false
}
