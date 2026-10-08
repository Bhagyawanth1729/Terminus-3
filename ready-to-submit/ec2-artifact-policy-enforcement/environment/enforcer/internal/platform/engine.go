package platform

import (
	"fmt"
	"time"
)

func decisionIDFromContext(context *EvaluationContext, code string) string {
	return stableID(
		context.Fingerprint(),
		context.SnapshotID,
		code,
		context.Now.UTC().Format(time.RFC3339),
	)
}

func baseContextDecision(context *EvaluationContext, verdict, code, message string) Decision {
	req := context.Request()
	return Decision{
		DecisionID:     decisionIDFromContext(context, code),
		RequestID:      req.RequestID,
		Decision:       verdict,
		Code:           code,
		Message:        message,
		PolicyVersion:  context.Compiled.Version,
		ArtifactDigest: req.Digest,
		EvaluatedAt:    context.Now.UTC().Format(time.RFC3339),
	}
}

func commitContextDecision(context *EvaluationContext, decision Decision) (Decision, error) {
	context.AddTrace(StageDecision, decision.Code, decision.Decision)
	return CommitAdmissionDecision(context, decision)
}

func denyContext(context *EvaluationContext, code, message string) (Decision, error) {
	return commitContextDecision(context, baseContextDecision(context, "DENY", code, message))
}

func allowContextWithException(context *EvaluationContext, exception Exception, secret []byte) (Decision, error) {
	decision := baseContextDecision(context, "ALLOW", "ALLOW_EXCEPTION", "policy overridden by approved exception")
	decision.ExceptionID = exception.ID
	issued := IssueAdmissionPermit(context, secret)
	decision.Permit = &issued.Permit
	return commitContextDecision(context, decision)
}

func allowContextClean(context *EvaluationContext, evidence EvidenceAssessment, secret []byte) (Decision, error) {
	decision := baseContextDecision(context, "ALLOW", "ALLOW_CLEAN", "artifact satisfies current software policy")
	decision.ScanDBRevision = evidence.ScannerDBRevision
	decision.CacheHit = evidence.CacheHit
	decision.Vulnerabilities = append([]Vulnerability(nil), evidence.Vulnerabilities...)
	issued := IssueAdmissionPermit(context, secret)
	decision.Permit = &issued.Permit
	return commitContextDecision(context, decision)
}

func denyFromEvidence(context *EvaluationContext, evidence EvidenceAssessment) (Decision, error) {
	decision := baseContextDecision(context, "DENY", evidence.FailureCode, evidence.FailureMessage)
	decision.ScanDBRevision = evidence.ScannerDBRevision
	decision.CacheHit = evidence.CacheHit
	decision.Vulnerabilities = append([]Vulnerability(nil), evidence.Vulnerabilities...)
	return commitContextDecision(context, decision)
}

func denyFromVulnerability(context *EvaluationContext, evidence EvidenceAssessment, vulnerability VulnerabilityDecision) (Decision, error) {
	decision := baseContextDecision(context, "DENY", vulnerability.FailureCode, vulnerability.FailureMessage)
	decision.ScanDBRevision = evidence.ScannerDBRevision
	decision.CacheHit = evidence.CacheHit
	decision.Vulnerabilities = append([]Vulnerability(nil), evidence.Vulnerabilities...)
	return commitContextDecision(context, decision)
}

// Evaluate executes one artifact admission through canonical request parsing,
// manager semantics, compiled policy, durable-state inspection, identity/source
// prerequisites, evidence acquisition, exception handling, permit issuance and
// persistence.  Intentional defects remain at documented starter seams so the
// solver has the approved repair work without the old dead catalog padding.
func Evaluate(policy Policy, scans ScanDB, exceptions ExceptionDB, req Request, stateDir string, secret []byte, now time.Time) (Decision, error) {
	context, err := PrepareEvaluation(policy, req, stateDir, now)
	if err != nil {
		return Decision{}, err
	}

	state, err := PrepareStateRuntime(context)
	if err != nil {
		return Decision{}, err
	}
	if err := ValidateStateForMutation(state); err != nil {
		return Decision{}, err
	}

	// Intentional starter ordering defect: the vulnerability exception lookup
	// is performed before digest/source/scanner prerequisites.  Q1/Q4 require
	// the repaired solution to move this waiver behind all prerequisites.
	earlyException := EvaluateExceptionPolicy(context, exceptions, "VULNERABILITY_THRESHOLD")
	if ExceptionAllows(earlyException) {
		return allowContextWithException(context, *earlyException.Matched, secret)
	}

	digest := EvaluateDigestPolicy(context)
	if digest.FailureCode != "" {
		context.AddTrace(StageIdentity, digest.FailureCode, digest.FailureMessage)
		return denyContext(context, digest.FailureCode, digest.FailureMessage)
	}
	context.AddTrace(StageIdentity, "DIGEST_ACCEPTED", context.Request().Digest)

	source := EvaluateSourcePolicy(context)
	if !source.Allowed {
		context.AddTrace(StageSource, source.FailureCode, source.FailureMessage)
		return denyContext(context, source.FailureCode, source.FailureMessage)
	}
	context.AddTrace(StageSource, "SOURCE_ACCEPTED", fmt.Sprintf("%s:%s", source.MatchKind, source.Canonical))

	evidence, err := ResolveEvidence(context, scans, stateDir)
	if err != nil {
		return Decision{}, err
	}
	if EvidenceRequiresDeny(evidence) {
		return denyFromEvidence(context, evidence)
	}

	vulnerability := EvaluateVulnerabilityPolicy(context, evidence.Vulnerabilities)
	if vulnerability.Denied {
		return denyFromVulnerability(context, evidence, vulnerability)
	}
	return allowContextClean(context, evidence, secret)
}
