package platform

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// JournalRecordState captures the physical and semantic status of one audit
// record without mutating the journal.
type JournalRecordState struct {
	Line       int
	Offset     int64
	Length     int
	Terminated bool
	Valid      bool
	Decision   Decision
	Error      string
}

// JournalInspection is used by the commit path to understand durable history
// before writing a new projection/journal record.
type JournalInspection struct {
	Path               string
	Exists             bool
	Size               int64
	Records            []JournalRecordState
	ValidDecisions     []Decision
	MalformedLines     []int
	UnterminatedFinal  bool
	InteriorCorruption bool
	LastValidOffset    int64
	LastRequestID      string
	LastDecisionID     string
}

// DecisionCommitPlan connects idempotency intent, durable history and the
// projection that will be materialized.
type DecisionCommitPlan struct {
	Decision           Decision
	Inspection         JournalInspection
	DuplicateRequest   bool
	DuplicateDecision  bool
	Existing           *Decision
	JournalRequired    bool
	ProjectionRequired bool
	PlanID             string
}

func inspectJournalBytes(path string, data []byte) JournalInspection {
	inspection := JournalInspection{Path: path, Exists: true, Size: int64(len(data))}
	if len(data) == 0 {
		return inspection
	}
	reader := bufio.NewReader(bytes.NewReader(data))
	offset := int64(0)
	line := 0
	for {
		chunk, err := reader.ReadBytes('\n')
		if len(chunk) == 0 && err != nil {
			break
		}
		line++
		terminated := len(chunk) > 0 && chunk[len(chunk)-1] == '\n'
		raw := bytes.TrimSuffix(chunk, []byte{'\n'})
		raw = bytes.TrimSuffix(raw, []byte{'\r'})
		record := JournalRecordState{
			Line:       line,
			Offset:     offset,
			Length:     len(chunk),
			Terminated: terminated,
		}
		if len(bytes.TrimSpace(raw)) == 0 {
			record.Error = "empty-record"
		} else if unmarshalErr := json.Unmarshal(raw, &record.Decision); unmarshalErr != nil {
			record.Error = unmarshalErr.Error()
		} else {
			record.Valid = true
			inspection.ValidDecisions = append(inspection.ValidDecisions, record.Decision)
			inspection.LastValidOffset = offset + int64(len(chunk))
			inspection.LastRequestID = record.Decision.RequestID
			inspection.LastDecisionID = record.Decision.DecisionID
		}
		inspection.Records = append(inspection.Records, record)
		if !record.Valid {
			inspection.MalformedLines = append(inspection.MalformedLines, line)
		}
		if !terminated {
			inspection.UnterminatedFinal = true
		}
		offset += int64(len(chunk))
		if err != nil {
			break
		}
	}
	for _, malformed := range inspection.MalformedLines {
		if malformed < len(inspection.Records) {
			inspection.InteriorCorruption = true
			break
		}
	}
	return inspection
}

func InspectJournal(path string) (JournalInspection, error) {
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return JournalInspection{Path: path}, nil
	}
	if err != nil {
		return JournalInspection{}, err
	}
	return inspectJournalBytes(path, data), nil
}

func findExistingDecision(inspection JournalInspection, decision Decision) (*Decision, bool, bool) {
	var requestMatch *Decision
	for i := range inspection.ValidDecisions {
		existing := inspection.ValidDecisions[i]
		if existing.DecisionID == decision.DecisionID {
			copy := existing
			return &copy, existing.RequestID == decision.RequestID, true
		}
		if existing.RequestID == decision.RequestID && existing.ArtifactDigest == decision.ArtifactDigest && existing.PolicyVersion == decision.PolicyVersion {
			copy := existing
			requestMatch = &copy
		}
	}
	return requestMatch, requestMatch != nil, false
}

func commitPlanID(decision Decision, inspection JournalInspection) string {
	return stableID(
		decision.DecisionID,
		decision.RequestID,
		decision.PolicyVersion,
		fmt.Sprintf("journal-size=%d", inspection.Size),
		fmt.Sprintf("records=%d", len(inspection.Records)),
	)
}

func BuildDecisionCommitPlan(context *EvaluationContext, decision Decision) (DecisionCommitPlan, error) {
	inspection, err := InspectJournal(context.Paths.AuditFile)
	if err != nil {
		return DecisionCommitPlan{}, err
	}
	existing, duplicateRequest, duplicateDecision := findExistingDecision(inspection, decision)
	plan := DecisionCommitPlan{
		Decision:           decision,
		Inspection:         inspection,
		DuplicateRequest:   duplicateRequest,
		DuplicateDecision:  duplicateDecision,
		Existing:           existing,
		JournalRequired:    true,
		ProjectionRequired: true,
	}
	plan.PlanID = commitPlanID(decision, inspection)
	return plan, nil
}

func journalInspectionSummary(inspection JournalInspection) string {
	return fmt.Sprintf(
		"exists=%t size=%d records=%d malformed=%v unterminated=%t interior=%t",
		inspection.Exists,
		inspection.Size,
		len(inspection.Records),
		inspection.MalformedLines,
		inspection.UnterminatedFinal,
		inspection.InteriorCorruption,
	)
}

// CommitAdmissionDecision is the single live completion path for evaluate.
// The starter intentionally retains the approved legacy ordering and duplicate
// behavior: projection is written before AppendAudit, duplicate requests are
// not collapsed, and AppendAudit itself omits denies.  The reference solution
// replaces these narrow persistence seams.
func CommitAdmissionDecision(context *EvaluationContext, decision Decision) (Decision, error) {
	plan, err := BuildDecisionCommitPlan(context, decision)
	if err != nil {
		return decision, err
	}
	context.AddTrace(StagePersistence, "JOURNAL_INSPECTED", journalInspectionSummary(plan.Inspection))
	if plan.Inspection.InteriorCorruption || len(plan.Inspection.MalformedLines) > 0 {
		return decision, fmt.Errorf("audit journal corruption: %s", JournalCorruptionDescription(plan.Inspection))
	}
	if plan.DuplicateDecision && plan.Existing != nil {
		context.AddTrace(StagePersistence, "IDEMPOTENT_REPLAY", plan.Existing.DecisionID)
		if err := WriteLastDecision(context.Paths.Root, *plan.Existing); err != nil {
			return decision, err
		}
		return *plan.Existing, nil
	}
	// Durable journal is authoritative: fsync it before advancing the derived
	// last-decision projection.
	if err := AppendAudit(context.Paths.Root, decision); err != nil {
		return decision, err
	}
	context.AddTrace(StagePersistence, "JOURNAL_DURABLE", decision.DecisionID)
	if err := WriteLastDecision(context.Paths.Root, decision); err != nil {
		return decision, err
	}
	context.AddTrace(StagePersistence, "PROJECTION_WRITTEN", decision.DecisionID)
	return decision, nil
}

func JournalRequestHistory(inspection JournalInspection, requestID string) []Decision {
	out := make([]Decision, 0, 4)
	for _, decision := range inspection.ValidDecisions {
		if decision.RequestID == requestID {
			out = append(out, decision)
		}
	}
	return out
}

func JournalDecisionByID(inspection JournalInspection, decisionID string) (Decision, bool) {
	for _, decision := range inspection.ValidDecisions {
		if decision.DecisionID == decisionID {
			return decision, true
		}
	}
	return Decision{}, false
}

func JournalHasDeny(inspection JournalInspection, requestID string) bool {
	for _, decision := range inspection.ValidDecisions {
		if decision.RequestID == requestID && decision.Decision == "DENY" {
			return true
		}
	}
	return false
}

func JournalHasAllow(inspection JournalInspection, requestID string) bool {
	for _, decision := range inspection.ValidDecisions {
		if decision.RequestID == requestID && decision.Decision == "ALLOW" {
			return true
		}
	}
	return false
}

func ProjectionConsistentWithJournal(projection Decision, inspection JournalInspection) bool {
	if projection.DecisionID == "" {
		return false
	}
	_, ok := JournalDecisionByID(inspection, projection.DecisionID)
	return ok
}

func JournalCorruptionDescription(inspection JournalInspection) string {
	if !inspection.InteriorCorruption && len(inspection.MalformedLines) == 0 {
		return "clean"
	}
	parts := make([]string, 0, 3)
	if inspection.InteriorCorruption {
		parts = append(parts, "interior-corruption")
	}
	if inspection.UnterminatedFinal {
		parts = append(parts, "unterminated-final")
	}
	if len(inspection.MalformedLines) > 0 {
		parts = append(parts, fmt.Sprintf("malformed-lines=%v", inspection.MalformedLines))
	}
	return strings.Join(parts, ",")
}

func JournalSummary(inspection JournalInspection) map[string]interface{} {
	return map[string]interface{}{
		"path":                inspection.Path,
		"exists":              inspection.Exists,
		"size":                inspection.Size,
		"record_count":        len(inspection.Records),
		"valid_count":         len(inspection.ValidDecisions),
		"malformed_lines":     append([]int(nil), inspection.MalformedLines...),
		"unterminated_final":  inspection.UnterminatedFinal,
		"interior_corruption": inspection.InteriorCorruption,
		"last_request_id":     inspection.LastRequestID,
		"last_decision_id":    inspection.LastDecisionID,
	}
}
