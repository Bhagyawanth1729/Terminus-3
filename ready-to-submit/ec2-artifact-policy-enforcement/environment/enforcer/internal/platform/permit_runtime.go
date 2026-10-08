package platform

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"
	"strings"
	"time"
)

// PermitClaims is the canonical authorization scope represented by a permit.
type PermitClaims struct {
	RequestID      string
	InstanceID     string
	ArtifactDigest string
	PolicyVersion  string
	IssuedAt       time.Time
	ExpiresAt      time.Time
	TTL            time.Duration
	ScopeID        string
}

// PermitIssueAssessment is used by the admission engine after successful
// policy evaluation.
type PermitIssueAssessment struct {
	Permit           Permit
	Claims           PermitClaims
	SecretPresent    bool
	SignaturePresent bool
	FieldsBound      bool
	Fingerprint      string
}

// PermitVerificationAssessment exposes both the legacy starter verdict and the
// strict binding facts.  The effective starter result intentionally preserves
// the approved instance/signing defect through VerifyPermit.
type PermitVerificationAssessment struct {
	LegacyValid      bool
	LegacyCode       string
	StrictValid      bool
	RequestMatches   bool
	InstanceMatches  bool
	DigestMatches    bool
	PolicyMatches    bool
	Unexpired        bool
	SignaturePresent bool
	SecretPresent    bool
	ScopeID          string
	FailureReasons   []string
}

func canonicalPermitScopeID(requestID, instanceID, digest, policyVersion string) string {
	return stableID(
		strings.TrimSpace(requestID),
		strings.TrimSpace(instanceID),
		strings.TrimSpace(digest),
		strings.TrimSpace(policyVersion),
	)
}

func permitClaimsFromContext(context *EvaluationContext) PermitClaims {
	req := context.Request()
	issued := context.Now.UTC()
	expires := issued.Add(context.Compiled.PermitTTL)
	return PermitClaims{
		RequestID:      req.RequestID,
		InstanceID:     req.InstanceID,
		ArtifactDigest: req.Digest,
		PolicyVersion:  context.Compiled.Version,
		IssuedAt:       issued,
		ExpiresAt:      expires,
		TTL:            context.Compiled.PermitTTL,
		ScopeID:        canonicalPermitScopeID(req.RequestID, req.InstanceID, req.Digest, context.Compiled.Version),
	}
}

func permitClaimsFromPermit(permit Permit, now time.Time) PermitClaims {
	expires, _ := parseRFC3339(permit.ExpiresAt)
	return PermitClaims{
		RequestID:      permit.RequestID,
		InstanceID:     permit.InstanceID,
		ArtifactDigest: permit.ArtifactDigest,
		PolicyVersion:  permit.PolicyVersion,
		IssuedAt:       time.Time{},
		ExpiresAt:      expires,
		TTL:            expires.Sub(now),
		ScopeID:        canonicalPermitScopeID(permit.RequestID, permit.InstanceID, permit.ArtifactDigest, permit.PolicyVersion),
	}
}

func permitIssueFingerprint(permit Permit, claims PermitClaims) string {
	return stableID(
		claims.ScopeID,
		claims.ExpiresAt.UTC().Format(time.RFC3339),
		permit.Signature,
	)
}

func permitFieldsBound(permit Permit, claims PermitClaims) bool {
	return permit.RequestID == claims.RequestID &&
		permit.InstanceID == claims.InstanceID &&
		permit.ArtifactDigest == claims.ArtifactDigest &&
		permit.PolicyVersion == claims.PolicyVersion &&
		permit.ExpiresAt == claims.ExpiresAt.UTC().Format(time.RFC3339)
}

// IssueAdmissionPermit is the only permit issuance path used by Evaluate.
// SignPermit remains the intentionally defective starter seam; the reference
// solution replaces that signer with HMAC while this lifecycle code remains.
func IssueAdmissionPermit(context *EvaluationContext, secret []byte) PermitIssueAssessment {
	claims := permitClaimsFromContext(context)
	permit := SignPermit(context.Request(), context.Policy, secret, context.Now)
	assessment := PermitIssueAssessment{
		Permit:           permit,
		Claims:           claims,
		SecretPresent:    len(secret) > 0,
		SignaturePresent: strings.TrimSpace(permit.Signature) != "",
		FieldsBound:      permitFieldsBound(permit, claims),
	}
	assessment.Fingerprint = permitIssueFingerprint(permit, claims)
	context.AddTrace(StagePermit, "PERMIT_ISSUED", claims.ScopeID+":"+assessment.Fingerprint)
	return assessment
}

func permitRequestMatches(permit Permit, req Request) bool {
	return strings.TrimSpace(permit.RequestID) == strings.TrimSpace(req.RequestID)
}

func permitInstanceMatches(permit Permit, req Request) bool {
	return strings.TrimSpace(permit.InstanceID) == strings.TrimSpace(req.InstanceID)
}

func permitDigestMatches(permit Permit, req Request) bool {
	return strings.TrimSpace(permit.ArtifactDigest) == strings.TrimSpace(req.Digest)
}

func permitPolicyMatches(permit Permit, policy Policy) bool {
	return strings.TrimSpace(permit.PolicyVersion) == strings.TrimSpace(policy.Version)
}

func permitUnexpired(permit Permit, now time.Time) bool {
	expires, err := parseRFC3339(permit.ExpiresAt)
	return err == nil && now.Before(expires)
}

func permitFailureReasons(permit Permit, req Request, policy Policy, secret []byte, now time.Time) []string {
	reasons := make([]string, 0, 8)
	if !permitRequestMatches(permit, req) {
		reasons = append(reasons, "request_id")
	}
	if !permitInstanceMatches(permit, req) {
		reasons = append(reasons, "instance_id")
	}
	if !permitDigestMatches(permit, req) {
		reasons = append(reasons, "artifact_digest")
	}
	if !permitPolicyMatches(permit, policy) {
		reasons = append(reasons, "policy_version")
	}
	if !permitUnexpired(permit, now) {
		reasons = append(reasons, "expiry")
	}
	if strings.TrimSpace(permit.Signature) == "" {
		reasons = append(reasons, "signature")
	}
	if len(secret) == 0 {
		reasons = append(reasons, "secret")
	}
	sort.Strings(reasons)
	return reasons
}

// VerifyAdmissionPermit makes the complete permit binding analysis reachable
// from the public verify-permit CLI.  LegacyValid remains authoritative in the
// starter so the approved unkeyed/instance-binding defects are retained.
func VerifyAdmissionPermit(permit Permit, req Request, policy Policy, secret []byte, now time.Time) PermitVerificationAssessment {
	req = NormalizeRequest(req)
	legacyValid, legacyCode := VerifyPermit(permit, req, policy, secret, now)
	reasons := permitFailureReasons(permit, req, policy, secret, now)
	assessment := PermitVerificationAssessment{
		LegacyValid:      legacyValid,
		LegacyCode:       legacyCode,
		RequestMatches:   permitRequestMatches(permit, req),
		InstanceMatches:  permitInstanceMatches(permit, req),
		DigestMatches:    permitDigestMatches(permit, req),
		PolicyMatches:    permitPolicyMatches(permit, policy),
		Unexpired:        permitUnexpired(permit, now),
		SignaturePresent: strings.TrimSpace(permit.Signature) != "",
		SecretPresent:    len(secret) > 0,
		FailureReasons:   reasons,
		ScopeID:          canonicalPermitScopeID(permit.RequestID, permit.InstanceID, permit.ArtifactDigest, permit.PolicyVersion),
	}
	assessment.StrictValid = len(reasons) == 0 && legacyValid
	return assessment
}

func EffectivePermitVerification(assessment PermitVerificationAssessment) (bool, string) {
	return assessment.LegacyValid, assessment.LegacyCode
}

func PermitVerificationSummary(assessment PermitVerificationAssessment) map[string]interface{} {
	return map[string]interface{}{
		"legacy_valid":      assessment.LegacyValid,
		"legacy_code":       assessment.LegacyCode,
		"strict_valid":      assessment.StrictValid,
		"request_matches":   assessment.RequestMatches,
		"instance_matches":  assessment.InstanceMatches,
		"digest_matches":    assessment.DigestMatches,
		"policy_matches":    assessment.PolicyMatches,
		"unexpired":         assessment.Unexpired,
		"signature_present": assessment.SignaturePresent,
		"secret_present":    assessment.SecretPresent,
		"scope_id":          assessment.ScopeID,
		"failure_reasons":   append([]string(nil), assessment.FailureReasons...),
	}
}

func PermitScopeDiff(permit Permit, req Request, policy Policy) map[string][2]string {
	diff := map[string][2]string{}
	if !permitRequestMatches(permit, req) {
		diff["request_id"] = [2]string{permit.RequestID, req.RequestID}
	}
	if !permitInstanceMatches(permit, req) {
		diff["instance_id"] = [2]string{permit.InstanceID, req.InstanceID}
	}
	if !permitDigestMatches(permit, req) {
		diff["artifact_digest"] = [2]string{permit.ArtifactDigest, req.Digest}
	}
	if !permitPolicyMatches(permit, policy) {
		diff["policy_version"] = [2]string{permit.PolicyVersion, policy.Version}
	}
	return diff
}

func PermitSignatureEntropyHint(signature string) int {
	signature = strings.TrimSpace(signature)
	if signature == "" {
		return 0
	}
	seen := map[rune]bool{}
	for _, ch := range signature {
		seen[ch] = true
	}
	return len(seen)
}

func PermitSignatureShape(permit Permit) (algorithm string, bytes int, validHex bool) {
	signature := strings.TrimSpace(permit.Signature)
	decoded, err := hex.DecodeString(signature)
	if err != nil {
		return "unknown", 0, false
	}
	switch len(decoded) {
	case sha256.Size:
		return "sha256-sized", len(decoded), true
	default:
		return "unknown", len(decoded), true
	}
}

func PermitOperationalDescription(permit Permit, now time.Time) string {
	claims := permitClaimsFromPermit(permit, now)
	algorithm, size, hexOK := PermitSignatureShape(permit)
	return fmt.Sprintf(
		"scope=%s expires=%s ttl=%s signature=%s/%d hex=%t",
		claims.ScopeID,
		claims.ExpiresAt.UTC().Format(time.RFC3339),
		claims.TTL,
		algorithm,
		size,
		hexOK,
	)
}
