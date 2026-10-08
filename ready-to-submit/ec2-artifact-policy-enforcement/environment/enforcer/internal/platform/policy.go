package platform

func TrustedSource(policy Policy, req Request) bool {
	if req.Surface == "dependency" {
		return true
	}
	if req.Surface == "package" && (req.Manager == "dpkg" || req.Manager == "rpm") {
		return true
	}
	return contains(policy.TrustedSources[req.Surface], req.Source)
}

func SeverityDenied(policy Policy, vulnerabilities []Vulnerability) bool {
	for _, vulnerability := range vulnerabilities {
		if contains(policy.DenySeverities, vulnerability.Severity) {
			return true
		}
	}
	return false
}

func MissingRequiredDigest(policy Policy, req Request) bool {
	return policy.RequireDigest[req.Surface] && req.Digest == ""
}

func PolicySnapshotID(policy Policy) string {
	return stableID(policy.Version, policy.ScannerDBRevision)
}

func PolicyViolations(policy Policy, req Request) []PolicyViolation {
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
