package platform

import (
	"fmt"
	"sort"
	"strings"
	"time"
)

// EvidenceSource identifies where the vulnerability evidence used by a
// decision came from.
type EvidenceSource string

const (
	EvidenceNone    EvidenceSource = "none"
	EvidenceCache   EvidenceSource = "cache"
	EvidenceScanner EvidenceSource = "scanner"
)

// CacheAssessment records both the strict cache invariants and the effective
// starter decision.  The reference solution changes only the intentional
// legacy acceptance rule; the rest of the cache workflow is production logic.
type CacheAssessment struct {
	Key             string
	Present         bool
	Decoded         bool
	ArtifactMatches bool
	PolicyMatches   bool
	ScannerMatches  bool
	Fresh           bool
	ExpiresAt       time.Time
	ScannedAt       time.Time
	Usable          bool
	Reason          string
	Entry           CacheEntry
}

// ScannerAssessment describes health, revision, data quality and normalized
// vulnerability content of the configured scanner record.
type ScannerAssessment struct {
	Digest          string
	Present         bool
	Healthy         bool
	RevisionMatches bool
	Status          string
	DBRevision      string
	Vulnerabilities []Vulnerability
	MaximumSeverity string
	Reason          string
}

// EvidenceAssessment is the complete evidence result consumed by the policy
// engine.  A caller cannot authorize an artifact without passing through this
// structure.
type EvidenceAssessment struct {
	Source              EvidenceSource
	Cache               CacheAssessment
	Scanner             ScannerAssessment
	ArtifactDigest      string
	PolicyVersion       string
	ScannerDBRevision   string
	Vulnerabilities     []Vulnerability
	CacheHit            bool
	FailureCode         string
	FailureMessage      string
	EvidenceFingerprint string
}

func evidenceKey(context *EvaluationContext) string {
	return CacheKey(context.Request(), context.Policy)
}

func parseCacheTime(value string) (time.Time, bool) {
	parsed, err := parseRFC3339(value)
	if err != nil {
		return time.Time{}, false
	}
	return parsed.UTC(), true
}

func assessCacheEntry(context *EvaluationContext, key string, entry CacheEntry, present bool) CacheAssessment {
	assessment := CacheAssessment{
		Key:     key,
		Present: present,
		Entry:   entry,
	}
	if !present {
		assessment.Reason = "cache-miss"
		return assessment
	}
	assessment.Decoded = entry.ArtifactDigest != "" || entry.PolicyVersion != "" || entry.ScanDBRevision != "" || entry.ExpiresAt != ""
	assessment.ArtifactMatches = entry.ArtifactDigest == context.Request().Digest
	assessment.PolicyMatches = entry.PolicyVersion == context.Compiled.Version
	assessment.ScannerMatches = entry.ScanDBRevision == context.Compiled.ScannerRevision
	if parsed, ok := parseCacheTime(entry.ExpiresAt); ok {
		assessment.ExpiresAt = parsed
		assessment.Fresh = context.Now.Before(parsed)
	}
	if parsed, ok := parseCacheTime(entry.ScannedAt); ok {
		assessment.ScannedAt = parsed
	}
	strictUsable := assessment.Decoded && assessment.ArtifactMatches && assessment.PolicyMatches && assessment.ScannerMatches && assessment.Fresh
	// Intentional starter defect: legacy admission treats any readable cache
	// path reported by LoadCache as usable.  This preserves the approved cache
	// identity/freshness defects while keeping the complete assessment live.
	assessment.Usable = strictUsable
	switch {
	case !assessment.Decoded:
		assessment.Reason = "cache-corrupt-or-partial"
	case !assessment.ArtifactMatches:
		assessment.Reason = "artifact-digest-mismatch"
	case !assessment.PolicyMatches:
		assessment.Reason = "policy-version-mismatch"
	case !assessment.ScannerMatches:
		assessment.Reason = "scanner-revision-mismatch"
	case !assessment.Fresh:
		assessment.Reason = "cache-expired"
	case strictUsable:
		assessment.Reason = "strict-cache-hit"
	default:
		assessment.Reason = "cache-unusable"
	}
	return assessment
}

func normalizeVulnerability(value Vulnerability) Vulnerability {
	value.ID = strings.TrimSpace(value.ID)
	value.Severity = canonicalSeverity(value.Severity)
	return value
}

func normalizeVulnerabilities(values []Vulnerability) []Vulnerability {
	seen := map[string]bool{}
	out := make([]Vulnerability, 0, len(values))
	for _, value := range values {
		value = normalizeVulnerability(value)
		if value.ID == "" {
			continue
		}
		key := value.ID + "\x00" + value.Severity
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, value)
	}
	sort.SliceStable(out, func(i, j int) bool {
		left := severityRanks[canonicalSeverity(out[i].Severity)]
		right := severityRanks[canonicalSeverity(out[j].Severity)]
		if left == right {
			return out[i].ID < out[j].ID
		}
		return left > right
	})
	return out
}

func assessScannerRecord(context *EvaluationContext, scans ScanDB) ScannerAssessment {
	digest := context.Request().Digest
	record, present := scans.Records[digest]
	if !present {
		record = ScanRecord{Status: "unavailable"}
	}
	vulnerabilities := normalizeVulnerabilities(record.Vulnerabilities)
	assessment := ScannerAssessment{
		Digest:          digest,
		Present:         present,
		Healthy:         ScannerHealthy(record),
		RevisionMatches: ScannerRevisionMatches(context.Policy, record),
		Status:          strings.ToLower(strings.TrimSpace(record.Status)),
		DBRevision:      strings.TrimSpace(record.DBRevision),
		Vulnerabilities: vulnerabilities,
		MaximumSeverity: maxSeverity(vulnerabilities),
	}
	switch {
	case !present:
		assessment.Reason = "scanner-record-missing"
	case !assessment.Healthy:
		assessment.Reason = "scanner-unavailable"
	case !assessment.RevisionMatches:
		assessment.Reason = "scanner-db-revision-stale"
	default:
		assessment.Reason = "scanner-current"
	}
	return assessment
}

func legacyScannerRecord(context *EvaluationContext, assessment ScannerAssessment) ScannerAssessment {
	// Repaired path: scanner health and DB-revision facts remain authoritative.
	return assessment
}

func cacheEntryFromScanner(context *EvaluationContext, scanner ScannerAssessment) CacheEntry {
	return CacheEntry{
		ArtifactDigest:  context.Request().Digest,
		PolicyVersion:   context.Compiled.Version,
		ScanDBRevision:  scanner.DBRevision,
		Vulnerabilities: append([]Vulnerability(nil), scanner.Vulnerabilities...),
		ScannedAt:       context.Now.UTC().Format(time.RFC3339),
		ExpiresAt:       context.Now.Add(context.Compiled.CacheTTL).UTC().Format(time.RFC3339),
	}
}

func evidenceFingerprint(source EvidenceSource, digest, policyVersion, scannerRevision string, vulnerabilities []Vulnerability) string {
	parts := []string{string(source), digest, policyVersion, scannerRevision}
	for _, vulnerability := range normalizeVulnerabilities(vulnerabilities) {
		parts = append(parts, vulnerability.ID+":"+canonicalSeverity(vulnerability.Severity))
	}
	return stableID(parts...)
}

func cacheAssessmentSummary(assessment CacheAssessment) string {
	return fmt.Sprintf(
		"key=%s present=%t decoded=%t artifact=%t policy=%t scanner=%t fresh=%t usable=%t reason=%s",
		assessment.Key,
		assessment.Present,
		assessment.Decoded,
		assessment.ArtifactMatches,
		assessment.PolicyMatches,
		assessment.ScannerMatches,
		assessment.Fresh,
		assessment.Usable,
		assessment.Reason,
	)
}

func scannerAssessmentSummary(assessment ScannerAssessment) string {
	return fmt.Sprintf(
		"digest=%s present=%t healthy=%t revision=%t status=%s db=%s vulns=%d reason=%s",
		assessment.Digest,
		assessment.Present,
		assessment.Healthy,
		assessment.RevisionMatches,
		assessment.Status,
		assessment.DBRevision,
		len(assessment.Vulnerabilities),
		assessment.Reason,
	)
}

func resolveFromCache(context *EvaluationContext, cache CacheAssessment) EvidenceAssessment {
	entry := cache.Entry
	assessment := EvidenceAssessment{
		Source:            EvidenceCache,
		Cache:             cache,
		ArtifactDigest:    context.Request().Digest,
		PolicyVersion:     context.Compiled.Version,
		ScannerDBRevision: entry.ScanDBRevision,
		Vulnerabilities:   normalizeVulnerabilities(entry.Vulnerabilities),
		CacheHit:          true,
	}
	assessment.EvidenceFingerprint = evidenceFingerprint(
		assessment.Source,
		assessment.ArtifactDigest,
		assessment.PolicyVersion,
		assessment.ScannerDBRevision,
		assessment.Vulnerabilities,
	)
	return assessment
}

func resolveFromScanner(context *EvaluationContext, scanner ScannerAssessment) EvidenceAssessment {
	assessment := EvidenceAssessment{
		Source:            EvidenceScanner,
		Scanner:           scanner,
		ArtifactDigest:    context.Request().Digest,
		PolicyVersion:     context.Compiled.Version,
		ScannerDBRevision: scanner.DBRevision,
		Vulnerabilities:   normalizeVulnerabilities(scanner.Vulnerabilities),
		CacheHit:          false,
	}
	assessment.EvidenceFingerprint = evidenceFingerprint(
		assessment.Source,
		assessment.ArtifactDigest,
		assessment.PolicyVersion,
		assessment.ScannerDBRevision,
		assessment.Vulnerabilities,
	)
	return assessment
}

func evidenceFailure(context *EvaluationContext, cache CacheAssessment, scanner ScannerAssessment, code, message string) EvidenceAssessment {
	return EvidenceAssessment{
		Source:            EvidenceNone,
		Cache:             cache,
		Scanner:           scanner,
		ArtifactDigest:    context.Request().Digest,
		PolicyVersion:     context.Compiled.Version,
		ScannerDBRevision: scanner.DBRevision,
		FailureCode:       code,
		FailureMessage:    message,
	}
}

// ResolveEvidence executes the actual cache/scanner decision for admission.
// Every evaluate call reaches this function after identity/source checks.
func ResolveEvidence(context *EvaluationContext, scans ScanDB, stateDir string) (EvidenceAssessment, error) {
	key := evidenceKey(context)
	entry, hit, err := LoadCache(stateDir, key, context.Now)
	if err != nil {
		return EvidenceAssessment{}, err
	}
	cache := assessCacheEntry(context, key, entry, hit)
	context.AddTrace(StageEvidence, "CACHE_ASSESSED", cacheAssessmentSummary(cache))
	if cache.Usable {
		assessment := resolveFromCache(context, cache)
		context.AddTrace(StageEvidence, "CACHE_SELECTED", assessment.EvidenceFingerprint)
		return assessment, nil
	}

	scanner := assessScannerRecord(context, scans)
	context.AddTrace(StageEvidence, "SCANNER_ASSESSED", scannerAssessmentSummary(scanner))
	effectiveScanner := legacyScannerRecord(context, scanner)
	if !effectiveScanner.Healthy {
		return evidenceFailure(context, cache, scanner, "DENY_SCANNER_UNAVAILABLE", "current scanner evidence is unavailable"), nil
	}
	if !effectiveScanner.RevisionMatches {
		return evidenceFailure(context, cache, scanner, "DENY_SCANNER_EVIDENCE_STALE", "scanner evidence revision does not match active policy"), nil
	}
	entry = cacheEntryFromScanner(context, effectiveScanner)
	if err := SaveCache(stateDir, key, entry); err != nil {
		return EvidenceAssessment{}, err
	}
	assessment := resolveFromScanner(context, effectiveScanner)
	assessment.Cache = cache
	assessment.Scanner = scanner
	context.AddTrace(StageEvidence, "SCANNER_SELECTED", assessment.EvidenceFingerprint)
	return assessment, nil
}

func EvidenceRequiresDeny(assessment EvidenceAssessment) bool {
	return assessment.FailureCode != ""
}

func EvidenceSummary(assessment EvidenceAssessment) map[string]interface{} {
	return map[string]interface{}{
		"source":               assessment.Source,
		"artifact_digest":      assessment.ArtifactDigest,
		"policy_version":       assessment.PolicyVersion,
		"scanner_db_revision":  assessment.ScannerDBRevision,
		"cache_hit":            assessment.CacheHit,
		"vulnerability_count":  len(assessment.Vulnerabilities),
		"evidence_fingerprint": assessment.EvidenceFingerprint,
		"failure_code":         assessment.FailureCode,
		"cache_reason":         assessment.Cache.Reason,
		"scanner_reason":       assessment.Scanner.Reason,
	}
}

func EvidenceAge(assessment EvidenceAssessment, now time.Time) time.Duration {
	if assessment.Source == EvidenceCache && !assessment.Cache.ScannedAt.IsZero() {
		return now.Sub(assessment.Cache.ScannedAt)
	}
	return 0
}

func EvidenceIsCurrentStrict(context *EvaluationContext, assessment EvidenceAssessment) bool {
	switch assessment.Source {
	case EvidenceCache:
		return assessment.Cache.Decoded &&
			assessment.Cache.ArtifactMatches &&
			assessment.Cache.PolicyMatches &&
			assessment.Cache.ScannerMatches &&
			assessment.Cache.Fresh
	case EvidenceScanner:
		return assessment.Scanner.Healthy && assessment.Scanner.RevisionMatches
	default:
		return false
	}
}

func EvidenceRiskFlags(context *EvaluationContext, assessment EvidenceAssessment) []string {
	flags := make([]string, 0, 8)
	if assessment.Source == EvidenceCache {
		if !assessment.Cache.Decoded {
			flags = append(flags, "CACHE_PARTIAL")
		}
		if !assessment.Cache.ArtifactMatches {
			flags = append(flags, "CACHE_DIGEST_MISMATCH")
		}
		if !assessment.Cache.PolicyMatches {
			flags = append(flags, "CACHE_POLICY_MISMATCH")
		}
		if !assessment.Cache.ScannerMatches {
			flags = append(flags, "CACHE_SCANNER_MISMATCH")
		}
		if !assessment.Cache.Fresh {
			flags = append(flags, "CACHE_EXPIRED")
		}
	}
	if assessment.Source == EvidenceScanner {
		if !assessment.Scanner.Healthy {
			flags = append(flags, "SCANNER_UNAVAILABLE")
		}
		if !assessment.Scanner.RevisionMatches {
			flags = append(flags, "SCANNER_REVISION_STALE")
		}
	}
	sort.Strings(flags)
	return flags
}
