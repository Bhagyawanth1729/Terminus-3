package platform

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/url"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// EvaluationStage names the externally meaningful phases of one admission
// decision.  The stage trace is intentionally derived from work that affects
// the result rather than being a logging-only side channel.
type EvaluationStage string

const (
	StageInput       EvaluationStage = "input"
	StageIdentity    EvaluationStage = "identity"
	StagePolicy      EvaluationStage = "policy"
	StageSource      EvaluationStage = "source"
	StageEvidence    EvaluationStage = "evidence"
	StageException   EvaluationStage = "exception"
	StageDecision    EvaluationStage = "decision"
	StagePermit      EvaluationStage = "permit"
	StagePersistence EvaluationStage = "persistence"
)

// StageTrace records deterministic phase facts that are also folded into the
// decision fingerprint.  This makes normalization and policy compilation part
// of the live decision semantics: changing a material phase input changes the
// fingerprint and idempotency identity.
type StageTrace struct {
	Stage   EvaluationStage
	Code    string
	Detail  string
	Ordinal int
}

// RequestEnvelope is the canonical request representation used after CLI JSON
// decoding.  It preserves the original request for diagnostics while carrying
// the normalized identity and manager-specific acquisition semantics.
type RequestEnvelope struct {
	Original           Request
	Request            Request
	Identity           ArtifactIdentity
	Profile            ManagerProfile
	Coordinate         string
	CanonicalSource    string
	RepositoryHost     string
	RepositoryPath     string
	ActionClass        string
	RequestFingerprint string
}

// StatePaths centralizes the durable files that participate in admission,
// replay and recovery.  Keeping these paths in one structure prevents each
// subsystem from inventing subtly different state locations.
type StatePaths struct {
	Root         string
	CacheDir     string
	ReplayDir    string
	TempDir      string
	AuditFile    string
	Projection   string
	StateLock    string
	RecoveryMark string
}

// EvaluationContext is the per-request state shared by policy, evidence,
// exception, permit and persistence subsystems.
type EvaluationContext struct {
	Envelope        RequestEnvelope
	Policy          Policy
	Compiled        CompiledPolicy
	Paths           StatePaths
	Now             time.Time
	Trace           []StageTrace
	SnapshotID      string
	DecisionSeed    string
	Warnings        []string
	OperationalTags map[string]string
}

func buildStatePaths(stateDir string) StatePaths {
	root := filepath.Clean(stateDir)
	return StatePaths{
		Root:         root,
		CacheDir:     filepath.Join(root, "cache"),
		ReplayDir:    filepath.Join(root, "replay"),
		TempDir:      filepath.Join(root, "tmp"),
		AuditFile:    filepath.Join(root, "audit.jsonl"),
		Projection:   filepath.Join(root, "last-decision.json"),
		StateLock:    filepath.Join(root, ".state.lock"),
		RecoveryMark: filepath.Join(root, ".recovery-required"),
	}
}

func appendTrace(trace []StageTrace, stage EvaluationStage, code, detail string) []StageTrace {
	return append(trace, StageTrace{Stage: stage, Code: code, Detail: detail, Ordinal: len(trace) + 1})
}

func canonicalRequestFingerprint(req Request, identity ArtifactIdentity, profile ManagerProfile, policy Policy) string {
	parts := []string{
		strings.TrimSpace(req.RequestID),
		strings.TrimSpace(req.InstanceID),
		strings.ToLower(strings.TrimSpace(req.Environment)),
		identity.Surface,
		identity.Manager,
		identity.Name,
		identity.Version,
		identity.Source,
		identity.Digest,
		strings.ToLower(strings.TrimSpace(req.Action)),
		profile.Name,
		policy.Version,
		policy.ScannerDBRevision,
	}
	sum := sha256.Sum256([]byte(strings.Join(parts, "\x00")))
	return hex.EncodeToString(sum[:])
}

func splitRepositorySource(source string) (host, path string) {
	source = strings.TrimSpace(source)
	if source == "" {
		return "", ""
	}
	candidate := source
	if !strings.Contains(candidate, "://") {
		candidate = "https://" + candidate
	}
	parsed, err := url.Parse(candidate)
	if err != nil || parsed.Host == "" {
		first, rest, ok := strings.Cut(source, "/")
		if !ok {
			return strings.ToLower(first), ""
		}
		return strings.ToLower(first), strings.Trim(rest, "/")
	}
	return strings.ToLower(parsed.Host), strings.Trim(parsed.Path, "/")
}

func normalizeCoordinatePart(value string) string {
	value = strings.TrimSpace(value)
	value = strings.ReplaceAll(value, "\x00", "")
	return value
}

func buildCoordinate(identity ArtifactIdentity) string {
	parts := []string{
		normalizeCoordinatePart(identity.Surface),
		normalizeCoordinatePart(identity.Manager),
		normalizeCoordinatePart(identity.Name),
		normalizeCoordinatePart(identity.Version),
		normalizeCoordinatePart(identity.Digest),
	}
	return strings.Join(parts, ":")
}

func validateIdentityShape(identity ArtifactIdentity) []PolicyViolation {
	violations := make([]PolicyViolation, 0, 8)
	if identity.Surface == "" {
		violations = append(violations, PolicyViolation{Code: "SURFACE_MISSING", Message: "artifact surface is required", Blocking: true})
	}
	if identity.Manager == "" {
		violations = append(violations, PolicyViolation{Code: "MANAGER_MISSING", Message: "artifact manager is required", Blocking: true})
	}
	if identity.Name == "" {
		violations = append(violations, PolicyViolation{Code: "NAME_MISSING", Message: "artifact name is required", Blocking: true})
	}
	if identity.Source == "" {
		violations = append(violations, PolicyViolation{Code: "SOURCE_MISSING", Message: "artifact source is required", Blocking: true})
	}
	if strings.ContainsAny(identity.Name, "\r\n\x00") {
		violations = append(violations, PolicyViolation{Code: "NAME_INVALID", Message: "artifact name contains a control delimiter", Blocking: true})
	}
	if strings.ContainsAny(identity.Source, "\r\n\x00") {
		violations = append(violations, PolicyViolation{Code: "SOURCE_INVALID", Message: "artifact source contains a control delimiter", Blocking: true})
	}
	return violations
}

func validateRequestMetadata(req Request) []PolicyViolation {
	violations := make([]PolicyViolation, 0, 8)
	if strings.TrimSpace(req.RequestID) == "" {
		violations = append(violations, PolicyViolation{Code: "REQUEST_ID_MISSING", Message: "request id is required", Blocking: true})
	}
	if strings.TrimSpace(req.InstanceID) == "" {
		violations = append(violations, PolicyViolation{Code: "INSTANCE_ID_MISSING", Message: "instance identity is required", Blocking: true})
	}
	if strings.TrimSpace(req.Environment) == "" {
		violations = append(violations, PolicyViolation{Code: "ENVIRONMENT_MISSING", Message: "environment is required", Blocking: true})
	}
	if len(req.RequestID) > 256 {
		violations = append(violations, PolicyViolation{Code: "REQUEST_ID_TOO_LONG", Message: "request id exceeds operational limit", Blocking: true})
	}
	if len(req.InstanceID) > 256 {
		violations = append(violations, PolicyViolation{Code: "INSTANCE_ID_TOO_LONG", Message: "instance id exceeds operational limit", Blocking: true})
	}
	return violations
}

func firstBlockingViolation(violations []PolicyViolation) *PolicyViolation {
	for i := range violations {
		if violations[i].Blocking {
			return &violations[i]
		}
	}
	return nil
}

func uniqueViolations(sets ...[]PolicyViolation) []PolicyViolation {
	seen := map[string]bool{}
	out := make([]PolicyViolation, 0, 16)
	for _, set := range sets {
		for _, violation := range set {
			key := violation.Code + "\x00" + violation.Message
			if seen[key] {
				continue
			}
			seen[key] = true
			out = append(out, violation)
		}
	}
	return out
}

func violationsError(violations []PolicyViolation) error {
	blocking := make([]string, 0, len(violations))
	for _, violation := range violations {
		if violation.Blocking {
			blocking = append(blocking, violation.Code+": "+violation.Message)
		}
	}
	if len(blocking) == 0 {
		return nil
	}
	sort.Strings(blocking)
	return fmt.Errorf("invalid acquisition request: %s", strings.Join(blocking, "; "))
}

func actionClass(profile ManagerProfile, action string) string {
	action = strings.ToLower(strings.TrimSpace(action))
	for _, value := range profile.InstallActions {
		if action == value {
			return "install"
		}
	}
	for _, value := range profile.UpdateActions {
		if action == value {
			return "update"
		}
	}
	for _, value := range profile.RemoveActions {
		if action == value {
			return "remove"
		}
	}
	if action == "" {
		return profile.DefaultActionClass
	}
	return "other"
}

func prepareEnvelope(req Request, policy Policy) (RequestEnvelope, []PolicyViolation) {
	original := req
	req = NormalizeRequest(req)
	identity := BuildIdentity(req)
	profile, ok := ResolveManagerProfile(identity.Surface, identity.Manager)
	violations := uniqueViolations(validateRequestMetadata(req), validateIdentityShape(identity))
	if !ok {
		violations = append(violations, PolicyViolation{
			Code:     "MANAGER_UNSUPPORTED",
			Message:  fmt.Sprintf("manager %q is unsupported for surface %q", identity.Manager, identity.Surface),
			Blocking: true,
		})
		profile = UnknownManagerProfile(identity.Surface, identity.Manager)
	}
	violations = append(violations, profile.ValidateRequest(req)...)
	host, path := splitRepositorySource(identity.Source)
	envelope := RequestEnvelope{
		Original:           original,
		Request:            req,
		Identity:           identity,
		Profile:            profile,
		Coordinate:         buildCoordinate(identity),
		CanonicalSource:    identity.Source,
		RepositoryHost:     host,
		RepositoryPath:     path,
		ActionClass:        actionClass(profile, req.Action),
		RequestFingerprint: canonicalRequestFingerprint(req, identity, profile, policy),
	}
	return envelope, violations
}

func deterministicTraceDigest(trace []StageTrace) string {
	parts := make([]string, 0, len(trace))
	for _, event := range trace {
		parts = append(parts, fmt.Sprintf("%03d|%s|%s|%s", event.Ordinal, event.Stage, event.Code, event.Detail))
	}
	sum := sha256.Sum256([]byte(strings.Join(parts, "\n")))
	return hex.EncodeToString(sum[:])
}

func deriveDecisionSeed(envelope RequestEnvelope, compiled CompiledPolicy, trace []StageTrace) string {
	return stableID(
		envelope.RequestFingerprint,
		compiled.SnapshotID,
		deterministicTraceDigest(trace),
	)
}

func operationalTags(envelope RequestEnvelope, compiled CompiledPolicy) map[string]string {
	return map[string]string{
		"surface":          envelope.Identity.Surface,
		"manager":          envelope.Identity.Manager,
		"environment":      envelope.Request.Environment,
		"action_class":     envelope.ActionClass,
		"repository_host":  envelope.RepositoryHost,
		"policy_snapshot":  compiled.SnapshotID,
		"scanner_revision": compiled.ScannerRevision,
	}
}

// PrepareEvaluation performs the operationally significant request and policy
// preparation used by every live evaluate call.
func PrepareEvaluation(policy Policy, req Request, stateDir string, now time.Time) (*EvaluationContext, error) {
	if stateDir == "" {
		return nil, fmt.Errorf("state directory is required")
	}
	if now.IsZero() {
		return nil, fmt.Errorf("evaluation time is required")
	}
	envelope, requestViolations := prepareEnvelope(req, policy)
	compiled, policyViolations := CompilePolicy(policy, envelope.Profile)
	violations := uniqueViolations(requestViolations, policyViolations)
	if err := violationsError(violations); err != nil {
		return nil, err
	}
	trace := make([]StageTrace, 0, 16)
	trace = appendTrace(trace, StageInput, "REQUEST_ACCEPTED", strings.TrimSpace(envelope.Request.RequestID))
	trace = appendTrace(trace, StageIdentity, "IDENTITY_CANONICAL", envelope.Coordinate)
	trace = appendTrace(trace, StagePolicy, "POLICY_COMPILED", compiled.SnapshotID)
	context := &EvaluationContext{
		Envelope:        envelope,
		Policy:          policy,
		Compiled:        compiled,
		Paths:           buildStatePaths(stateDir),
		Now:             now.UTC(),
		Trace:           trace,
		SnapshotID:      compiled.SnapshotID,
		Warnings:        make([]string, 0, 4),
		OperationalTags: operationalTags(envelope, compiled),
	}
	context.DecisionSeed = deriveDecisionSeed(envelope, compiled, trace)
	return context, nil
}

func (context *EvaluationContext) AddTrace(stage EvaluationStage, code, detail string) {
	context.Trace = appendTrace(context.Trace, stage, code, detail)
	context.DecisionSeed = deriveDecisionSeed(context.Envelope, context.Compiled, context.Trace)
}

func (context *EvaluationContext) AddWarning(message string) {
	message = strings.TrimSpace(message)
	if message == "" {
		return
	}
	for _, existing := range context.Warnings {
		if existing == message {
			return
		}
	}
	context.Warnings = append(context.Warnings, message)
}

func (context *EvaluationContext) Request() Request {
	return context.Envelope.Request
}

func (context *EvaluationContext) Identity() ArtifactIdentity {
	return context.Envelope.Identity
}

func (context *EvaluationContext) Fingerprint() string {
	return context.Envelope.RequestFingerprint
}

func (context *EvaluationContext) TraceDigest() string {
	return deterministicTraceDigest(context.Trace)
}

func (context *EvaluationContext) Tag(name string) string {
	return context.OperationalTags[name]
}
