package platform

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"
	"strings"
	"time"
)

// CompiledPolicy is the immutable policy view used for one decision.  It
// removes repeated map interpretation from each phase and makes the policy
// snapshot an explicit participant in cache, permit and audit semantics.
type CompiledPolicy struct {
	Version           string
	ScannerRevision   string
	SnapshotID        string
	DenySeveritySet   map[string]bool
	TrustedBySurface  map[string][]string
	DigestRequired    map[string]bool
	CacheTTL          time.Duration
	PermitTTL         time.Duration
	SupportedSurfaces map[string]bool
	ProfileSurface    string
	ProfileManager    string
}

// SourceDecision carries the evidence behind trusted-source admission.
type SourceDecision struct {
	Allowed        bool
	Surface        string
	Manager        string
	Canonical      string
	Host           string
	Configured     []string
	Matched        string
	MatchKind      string
	FailureCode    string
	FailureMessage string
}

// DigestDecision separates digest presence/shape from source and scanner
// evidence.  This ordering is important because exceptions are not allowed to
// waive artifact identity prerequisites in the repaired implementation.
type DigestDecision struct {
	Required       bool
	Present        bool
	Algorithm      string
	Value          string
	ValidShape     bool
	FailureCode    string
	FailureMessage string
}

// VulnerabilityDecision is the policy-side interpretation of scanner output.
type VulnerabilityDecision struct {
	Denied          bool
	Blocking        []Vulnerability
	Observed        []Vulnerability
	MaximumSeverity string
	DenySeverities  []string
	FailureCode     string
	FailureMessage  string
}

var severityRanks = map[string]int{
	"UNKNOWN":    0,
	"NONE":       0,
	"NEGLIGIBLE": 1,
	"LOW":        2,
	"MEDIUM":     3,
	"HIGH":       4,
	"CRITICAL":   5,
}

func canonicalSeverity(value string) string {
	value = strings.ToUpper(strings.TrimSpace(value))
	if value == "" {
		return "UNKNOWN"
	}
	if _, ok := severityRanks[value]; !ok {
		return "UNKNOWN"
	}
	return value
}

func cloneStringSlice(values []string) []string {
	out := make([]string, len(values))
	copy(out, values)
	return out
}

func cloneTrustedSources(values map[string][]string) map[string][]string {
	out := make(map[string][]string, len(values))
	for surface, sources := range values {
		canonicalSurface := normalizeSurface(surface)
		seen := map[string]bool{}
		for _, source := range sources {
			source = normalizeSource(source)
			if source == "" || seen[source] {
				continue
			}
			seen[source] = true
			out[canonicalSurface] = append(out[canonicalSurface], source)
		}
		sort.Strings(out[canonicalSurface])
	}
	return out
}

func cloneDigestPolicy(values map[string]bool) map[string]bool {
	out := make(map[string]bool, len(values))
	for surface, required := range values {
		out[normalizeSurface(surface)] = required
	}
	return out
}

func compiledPolicyDigest(policy Policy, trusted map[string][]string, required map[string]bool) string {
	parts := []string{
		"version=" + strings.TrimSpace(policy.Version),
		"scanner=" + strings.TrimSpace(policy.ScannerDBRevision),
		fmt.Sprintf("cache_ttl=%d", policy.CacheTTLSeconds),
		fmt.Sprintf("permit_ttl=%d", policy.PermitTTLSeconds),
	}
	severities := make([]string, 0, len(policy.DenySeverities))
	for _, severity := range policy.DenySeverities {
		severities = append(severities, canonicalSeverity(severity))
	}
	sort.Strings(severities)
	parts = append(parts, "deny="+strings.Join(severities, ","))
	surfaces := make([]string, 0, len(trusted)+len(required))
	seen := map[string]bool{}
	for surface := range trusted {
		seen[surface] = true
		surfaces = append(surfaces, surface)
	}
	for surface := range required {
		if !seen[surface] {
			surfaces = append(surfaces, surface)
		}
	}
	sort.Strings(surfaces)
	for _, surface := range surfaces {
		parts = append(parts, "trusted:"+surface+"="+strings.Join(trusted[surface], ","))
		parts = append(parts, fmt.Sprintf("digest:%s=%t", surface, required[surface]))
	}
	sum := sha256.Sum256([]byte(strings.Join(parts, "\n")))
	return hex.EncodeToString(sum[:])
}

func policyConfigurationViolations(policy Policy, profile ManagerProfile) []PolicyViolation {
	violations := make([]PolicyViolation, 0, 12)
	if strings.TrimSpace(policy.Version) == "" {
		violations = append(violations, PolicyViolation{Code: "POLICY_VERSION_MISSING", Message: "policy version is required", Blocking: true})
	}
	if strings.TrimSpace(policy.ScannerDBRevision) == "" {
		violations = append(violations, PolicyViolation{Code: "SCANNER_REVISION_MISSING", Message: "scanner DB revision is required", Blocking: true})
	}
	if policy.CacheTTLSeconds <= 0 {
		violations = append(violations, PolicyViolation{Code: "CACHE_TTL_INVALID", Message: "cache TTL must be positive", Blocking: true})
	}
	if policy.PermitTTLSeconds <= 0 {
		violations = append(violations, PolicyViolation{Code: "PERMIT_TTL_INVALID", Message: "permit TTL must be positive", Blocking: true})
	}
	if policy.CacheTTLSeconds > int64((7 * 24 * time.Hour).Seconds()) {
		violations = append(violations, PolicyViolation{Code: "CACHE_TTL_UNSAFE", Message: "cache TTL exceeds seven-day operational maximum", Blocking: true})
	}
	if policy.PermitTTLSeconds > int64((24 * time.Hour).Seconds()) {
		violations = append(violations, PolicyViolation{Code: "PERMIT_TTL_UNSAFE", Message: "permit TTL exceeds one-day operational maximum", Blocking: true})
	}
	if len(policy.DenySeverities) == 0 {
		violations = append(violations, PolicyViolation{Code: "DENY_SEVERITIES_EMPTY", Message: "at least one denied vulnerability severity is required", Blocking: true})
	}
	for _, severity := range policy.DenySeverities {
		canonical := canonicalSeverity(severity)
		if canonical == "UNKNOWN" && strings.ToUpper(strings.TrimSpace(severity)) != "UNKNOWN" {
			violations = append(violations, PolicyViolation{Code: "DENY_SEVERITY_INVALID", Message: fmt.Sprintf("unknown severity %q", severity), Blocking: true})
		}
	}
	if profile.Surface != "" {
		if _, ok := policy.TrustedSources[profile.Surface]; !ok {
			violations = append(violations, PolicyViolation{Code: "TRUST_POLICY_MISSING", Message: fmt.Sprintf("trusted sources missing for %s", profile.Surface), Blocking: true})
		}
		if _, ok := policy.RequireDigest[profile.Surface]; !ok {
			violations = append(violations, PolicyViolation{Code: "DIGEST_POLICY_MISSING", Message: fmt.Sprintf("digest policy missing for %s", profile.Surface), Blocking: true})
		}
	}
	return violations
}

func CompilePolicy(policy Policy, profile ManagerProfile) (CompiledPolicy, []PolicyViolation) {
	violations := policyConfigurationViolations(policy, profile)
	trusted := cloneTrustedSources(policy.TrustedSources)
	required := cloneDigestPolicy(policy.RequireDigest)
	deny := map[string]bool{}
	for _, severity := range policy.DenySeverities {
		deny[canonicalSeverity(severity)] = true
	}
	surfaces := map[string]bool{}
	for _, surface := range []string{"package", "container", "dependency"} {
		surfaces[surface] = true
	}
	compiled := CompiledPolicy{
		Version:           strings.TrimSpace(policy.Version),
		ScannerRevision:   strings.TrimSpace(policy.ScannerDBRevision),
		DenySeveritySet:   deny,
		TrustedBySurface:  trusted,
		DigestRequired:    required,
		CacheTTL:          time.Duration(policy.CacheTTLSeconds) * time.Second,
		PermitTTL:         time.Duration(policy.PermitTTLSeconds) * time.Second,
		SupportedSurfaces: surfaces,
		ProfileSurface:    profile.Surface,
		ProfileManager:    profile.Name,
	}
	compiled.SnapshotID = compiledPolicyDigest(policy, trusted, required)
	return compiled, violations
}

func sourceEquivalent(configured, observed string) bool {
	configured = normalizeSource(configured)
	observed = normalizeSource(observed)
	if configured == observed {
		return true
	}
	configuredHost, configuredPath := splitRepositorySource(configured)
	observedHost, observedPath := splitRepositorySource(observed)
	if configuredHost == "" || observedHost == "" || configuredHost != observedHost {
		return false
	}
	if configuredPath == "" {
		return true
	}
	return observedPath == configuredPath || strings.HasPrefix(observedPath, strings.TrimSuffix(configuredPath, "/")+"/")
}

func matchConfiguredSource(configured []string, observed string) (string, string) {
	for _, candidate := range configured {
		if normalizeSource(candidate) == normalizeSource(observed) {
			return candidate, "exact"
		}
	}
	for _, candidate := range configured {
		if sourceEquivalent(candidate, observed) {
			return candidate, "repository-prefix"
		}
	}
	return "", "none"
}

// EvaluateSourcePolicy deliberately delegates the ultimate allow/deny bit to
// TrustedSource.  The starter's intentional alternate-manager trust defects
// therefore remain observable while all surrounding source analysis is real
// and runtime-reachable.  The reference solution repairs TrustedSource.
func EvaluateSourcePolicy(context *EvaluationContext) SourceDecision {
	req := context.Request()
	configured := cloneStringSlice(context.Compiled.TrustedBySurface[req.Surface])
	matched, kind := matchConfiguredSource(configured, req.Source)
	host, _ := splitRepositorySource(req.Source)
	allowed := TrustedSource(context.Policy, req)
	decision := SourceDecision{
		Allowed:    allowed,
		Surface:    req.Surface,
		Manager:    req.Manager,
		Canonical:  normalizeSource(req.Source),
		Host:       host,
		Configured: configured,
		Matched:    matched,
		MatchKind:  kind,
	}
	if !allowed {
		decision.FailureCode = "DENY_UNTRUSTED_SOURCE"
		decision.FailureMessage = fmt.Sprintf("source %q is not trusted for %s", req.Source, req.Surface)
	}
	return decision
}

func parseDigest(digest string) (algorithm, value string, ok bool) {
	digest = strings.TrimSpace(digest)
	if digest == "" {
		return "", "", false
	}
	algorithm, value, found := strings.Cut(digest, ":")
	if !found {
		return "", digest, len(digest) >= 32
	}
	algorithm = strings.ToLower(strings.TrimSpace(algorithm))
	value = strings.ToLower(strings.TrimSpace(value))
	if algorithm == "sha256" && len(value) != 64 {
		return algorithm, value, false
	}
	if algorithm == "sha512" && len(value) != 128 {
		return algorithm, value, false
	}
	if value == "" {
		return algorithm, value, false
	}
	for _, ch := range value {
		if (ch < '0' || ch > '9') && (ch < 'a' || ch > 'f') {
			return algorithm, value, false
		}
	}
	return algorithm, value, true
}

func EvaluateDigestPolicy(context *EvaluationContext) DigestDecision {
	req := context.Request()
	required := context.Compiled.DigestRequired[req.Surface]
	algorithm, value, shapeOK := parseDigest(req.Digest)
	decision := DigestDecision{
		Required:   required,
		Present:    strings.TrimSpace(req.Digest) != "",
		Algorithm:  algorithm,
		Value:      value,
		ValidShape: shapeOK,
	}
	if MissingRequiredDigest(context.Policy, req) {
		decision.FailureCode = "DENY_MISSING_DIGEST"
		decision.FailureMessage = "immutable artifact digest is required"
		return decision
	}
	if decision.Present && !decision.ValidShape {
		decision.FailureCode = "DENY_INVALID_DIGEST"
		decision.FailureMessage = "artifact digest has an invalid immutable identity shape"
	}
	return decision
}

func severityGreater(left, right string) bool {
	return severityRanks[canonicalSeverity(left)] > severityRanks[canonicalSeverity(right)]
}

func sortVulnerabilities(values []Vulnerability) []Vulnerability {
	out := append([]Vulnerability(nil), values...)
	sort.SliceStable(out, func(i, j int) bool {
		li := severityRanks[canonicalSeverity(out[i].Severity)]
		lj := severityRanks[canonicalSeverity(out[j].Severity)]
		if li == lj {
			return out[i].ID < out[j].ID
		}
		return li > lj
	})
	return out
}

func EvaluateVulnerabilityPolicy(context *EvaluationContext, vulnerabilities []Vulnerability) VulnerabilityDecision {
	ordered := sortVulnerabilities(vulnerabilities)
	blocking := make([]Vulnerability, 0, len(ordered))
	max := "NONE"
	for _, vulnerability := range ordered {
		severity := canonicalSeverity(vulnerability.Severity)
		if severityGreater(severity, max) {
			max = severity
		}
		if context.Compiled.DenySeveritySet[severity] {
			blocking = append(blocking, vulnerability)
		}
	}
	denyValues := make([]string, 0, len(context.Compiled.DenySeveritySet))
	for severity := range context.Compiled.DenySeveritySet {
		denyValues = append(denyValues, severity)
	}
	sort.Strings(denyValues)
	decision := VulnerabilityDecision{
		Denied:          SeverityDenied(context.Policy, vulnerabilities),
		Blocking:        blocking,
		Observed:        ordered,
		MaximumSeverity: max,
		DenySeverities:  denyValues,
	}
	if decision.Denied {
		decision.FailureCode = "DENY_VULNERABLE"
		decision.FailureMessage = "artifact exceeds vulnerability severity policy"
	}
	return decision
}

func PolicyDecisionSummary(context *EvaluationContext, source SourceDecision, digest DigestDecision, vulnerability VulnerabilityDecision) map[string]interface{} {
	return map[string]interface{}{
		"snapshot_id":        context.Compiled.SnapshotID,
		"policy_version":     context.Compiled.Version,
		"scanner_revision":   context.Compiled.ScannerRevision,
		"surface":            context.Envelope.Identity.Surface,
		"manager":            context.Envelope.Identity.Manager,
		"source_allowed":     source.Allowed,
		"source_match_kind":  source.MatchKind,
		"digest_required":    digest.Required,
		"digest_present":     digest.Present,
		"digest_shape_valid": digest.ValidShape,
		"vulnerability_deny": vulnerability.Denied,
		"max_severity":       vulnerability.MaximumSeverity,
	}
}
