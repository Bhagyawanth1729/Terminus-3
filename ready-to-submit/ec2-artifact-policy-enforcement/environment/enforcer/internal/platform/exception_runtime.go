package platform

import (
	"fmt"
	"sort"
	"strings"
	"time"
)

// ExceptionCandidateAssessment explains every material scope dimension for an
// exception candidate.  The list is used to choose the effective waiver and
// to distinguish no-match from expired/wrong-scope state during diagnostics.
type ExceptionCandidateAssessment struct {
	ID                 string
	Name               string
	Digest             string
	PolicyCode         string
	PolicyCodeMatches  bool
	DigestMatches      bool
	NameMatches        bool
	SurfaceMatches     bool
	EnvironmentMatches bool
	Unexpired          bool
	ExpiresAt          time.Time
	StrictEligible     bool
	Reason             string
}

// ExceptionAssessment is consumed by the vulnerability decision path.
type ExceptionAssessment struct {
	PolicyCode     string
	Matched        *Exception
	CandidateCount int
	Candidates     []ExceptionCandidateAssessment
	StrictMatch    bool
	FailureReasons []string
	Fingerprint    string
}

func exceptionExpiry(candidate Exception) (time.Time, bool) {
	value, err := parseRFC3339(candidate.ExpiresAt)
	if err != nil {
		return time.Time{}, false
	}
	return value.UTC(), true
}

func candidatePolicyCodeMatches(candidate Exception, policyCode string) bool {
	return contains(candidate.PolicyCodes, policyCode)
}

func candidateNameMatches(candidate Exception, req Request) bool {
	if strings.TrimSpace(candidate.Name) == "" {
		return false
	}
	return strings.TrimSpace(candidate.Name) == strings.TrimSpace(req.Name)
}

func assessExceptionCandidate(candidate Exception, req Request, policyCode string, now time.Time) ExceptionCandidateAssessment {
	expires, validExpiry := exceptionExpiry(candidate)
	assessment := ExceptionCandidateAssessment{
		ID:                 strings.TrimSpace(candidate.ID),
		Name:               strings.TrimSpace(candidate.Name),
		Digest:             strings.TrimSpace(candidate.Digest),
		PolicyCode:         policyCode,
		PolicyCodeMatches:  candidatePolicyCodeMatches(candidate, policyCode),
		DigestMatches:      ExceptionDigestMatches(candidate, req),
		NameMatches:        candidateNameMatches(candidate, req),
		SurfaceMatches:     ExceptionSurfaceMatches(candidate, req),
		EnvironmentMatches: ExceptionEnvironmentMatches(candidate, req),
		Unexpired:          validExpiry && now.Before(expires),
		ExpiresAt:          expires,
	}
	assessment.StrictEligible = assessment.PolicyCodeMatches &&
		assessment.DigestMatches &&
		assessment.SurfaceMatches &&
		assessment.EnvironmentMatches &&
		assessment.Unexpired
	switch {
	case assessment.StrictEligible:
		assessment.Reason = "exact-current-scope"
	case !assessment.PolicyCodeMatches:
		assessment.Reason = "policy-code-mismatch"
	case !assessment.DigestMatches:
		assessment.Reason = "artifact-digest-mismatch"
	case !assessment.SurfaceMatches:
		assessment.Reason = "surface-mismatch"
	case !assessment.EnvironmentMatches:
		assessment.Reason = "environment-mismatch"
	case !assessment.Unexpired:
		assessment.Reason = "expired-or-invalid-expiry"
	default:
		assessment.Reason = "scope-mismatch"
	}
	return assessment
}

func exceptionAssessmentFingerprint(policyCode string, candidates []ExceptionCandidateAssessment) string {
	parts := []string{policyCode}
	ordered := append([]ExceptionCandidateAssessment(nil), candidates...)
	sort.SliceStable(ordered, func(i, j int) bool {
		if ordered[i].ID == ordered[j].ID {
			return ordered[i].Reason < ordered[j].Reason
		}
		return ordered[i].ID < ordered[j].ID
	})
	for _, candidate := range ordered {
		parts = append(parts, fmt.Sprintf(
			"%s|%s|%s|%t|%t|%t|%t|%t|%s",
			candidate.ID,
			candidate.Name,
			candidate.Digest,
			candidate.PolicyCodeMatches,
			candidate.DigestMatches,
			candidate.SurfaceMatches,
			candidate.EnvironmentMatches,
			candidate.Unexpired,
			candidate.Reason,
		))
	}
	return stableID(parts...)
}

func strictExceptionMatch(db ExceptionDB, req Request, policyCode string, now time.Time) *Exception {
	for i := range db.Exceptions {
		candidate := db.Exceptions[i]
		assessment := assessExceptionCandidate(candidate, req, policyCode, now)
		if assessment.StrictEligible {
			copy := candidate
			return &copy
		}
	}
	return nil
}

func collectExceptionReasons(candidates []ExceptionCandidateAssessment) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(candidates))
	for _, candidate := range candidates {
		if candidate.StrictEligible || seen[candidate.Reason] {
			continue
		}
		seen[candidate.Reason] = true
		out = append(out, candidate.Reason)
	}
	sort.Strings(out)
	return out
}

// EvaluateExceptionPolicy performs the full scope walk on every vulnerability
// decision.  The starter intentionally asks the legacy ExceptionFor helper for
// the effective match, preserving approved expiry/name/surface/environment
// defects.  The solution repairs ExceptionFor; the surrounding pipeline stays
// unchanged.
func EvaluateExceptionPolicy(context *EvaluationContext, db ExceptionDB, policyCode string) ExceptionAssessment {
	req := context.Request()
	candidates := make([]ExceptionCandidateAssessment, 0, len(db.Exceptions))
	for _, candidate := range db.Exceptions {
		candidates = append(candidates, assessExceptionCandidate(candidate, req, policyCode, context.Now))
	}
	strict := strictExceptionMatch(db, req, policyCode, context.Now)
	legacy := ExceptionFor(db, req, policyCode, context.Now)
	assessment := ExceptionAssessment{
		PolicyCode:     policyCode,
		Matched:        legacy,
		CandidateCount: len(candidates),
		Candidates:     candidates,
		StrictMatch:    strict != nil,
		FailureReasons: collectExceptionReasons(candidates),
	}
	assessment.Fingerprint = exceptionAssessmentFingerprint(policyCode, candidates)
	if legacy != nil {
		context.AddTrace(StageException, "EXCEPTION_SELECTED", legacy.ID+":"+assessment.Fingerprint)
	} else {
		context.AddTrace(StageException, "EXCEPTION_NONE", assessment.Fingerprint)
	}
	return assessment
}

func ExceptionAllows(assessment ExceptionAssessment) bool {
	return assessment.Matched != nil
}

func ExceptionID(assessment ExceptionAssessment) string {
	if assessment.Matched == nil {
		return ""
	}
	return assessment.Matched.ID
}

func ExceptionAssessmentSummary(assessment ExceptionAssessment) map[string]interface{} {
	matched := ""
	if assessment.Matched != nil {
		matched = assessment.Matched.ID
	}
	return map[string]interface{}{
		"policy_code":     assessment.PolicyCode,
		"matched_id":      matched,
		"candidate_count": assessment.CandidateCount,
		"strict_match":    assessment.StrictMatch,
		"failure_reasons": append([]string(nil), assessment.FailureReasons...),
		"fingerprint":     assessment.Fingerprint,
	}
}

func ExceptionCandidateByID(assessment ExceptionAssessment, id string) (ExceptionCandidateAssessment, bool) {
	for _, candidate := range assessment.Candidates {
		if candidate.ID == id {
			return candidate, true
		}
	}
	return ExceptionCandidateAssessment{}, false
}

func ExceptionScopeDifferences(candidate ExceptionCandidateAssessment) []string {
	differences := make([]string, 0, 5)
	if !candidate.PolicyCodeMatches {
		differences = append(differences, "policy_code")
	}
	if !candidate.DigestMatches {
		differences = append(differences, "digest")
	}
	if !candidate.SurfaceMatches {
		differences = append(differences, "surface")
	}
	if !candidate.EnvironmentMatches {
		differences = append(differences, "environment")
	}
	if !candidate.Unexpired {
		differences = append(differences, "expiry")
	}
	return differences
}

func ExceptionNearMatches(assessment ExceptionAssessment) []ExceptionCandidateAssessment {
	out := make([]ExceptionCandidateAssessment, 0, len(assessment.Candidates))
	for _, candidate := range assessment.Candidates {
		diff := ExceptionScopeDifferences(candidate)
		if len(diff) == 1 {
			out = append(out, candidate)
		}
	}
	return out
}

func ExceptionPolicyCodeCoverage(db ExceptionDB) map[string]int {
	coverage := map[string]int{}
	for _, candidate := range db.Exceptions {
		for _, code := range candidate.PolicyCodes {
			code = strings.TrimSpace(code)
			if code != "" {
				coverage[code]++
			}
		}
	}
	return coverage
}
