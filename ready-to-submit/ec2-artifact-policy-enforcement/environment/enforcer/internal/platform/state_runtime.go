package platform

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type StateFileStatus struct {
	Path       string
	Exists     bool
	Directory  bool
	Size       int64
	Mode       os.FileMode
	ModifiedAt time.Time
}

type StateRuntime struct {
	Paths            StatePaths
	Cache            StateFileStatus
	Replay           StateFileStatus
	Audit            StateFileStatus
	Projection       StateFileStatus
	Lock             StateFileStatus
	RecoveryRequired bool
	AuditLines       int
	ReplayLines      int
	Warnings         []string
}

func inspectStatePath(path string) (StateFileStatus, error) {
	status := StateFileStatus{Path: path}
	info, err := os.Stat(path)
	if os.IsNotExist(err) {
		return status, nil
	}
	if err != nil {
		return status, err
	}
	status.Exists = true
	status.Directory = info.IsDir()
	status.Size = info.Size()
	status.Mode = info.Mode()
	status.ModifiedAt = info.ModTime().UTC()
	return status, nil
}

func countStateLines(path string) (int, error) {
	file, err := os.Open(path)
	if os.IsNotExist(err) {
		return 0, nil
	}
	if err != nil {
		return 0, err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	count := 0
	for scanner.Scan() {
		if strings.TrimSpace(scanner.Text()) != "" {
			count++
		}
	}
	return count, scanner.Err()
}

func validateStateRoot(paths StatePaths) error {
	if strings.TrimSpace(paths.Root) == "" || paths.Root == "." {
		return fmt.Errorf("state root must be an explicit directory")
	}
	clean := filepath.Clean(paths.Root)
	if clean == string(filepath.Separator) {
		return fmt.Errorf("state root cannot be filesystem root")
	}
	for _, path := range []string{paths.CacheDir, paths.ReplayDir, paths.TempDir, paths.AuditFile, paths.Projection, paths.StateLock} {
		rel, err := filepath.Rel(clean, path)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return fmt.Errorf("state path escapes root: %s", path)
		}
	}
	return nil
}

func stateWarnings(runtime StateRuntime) []string {
	warnings := make([]string, 0, 8)
	if runtime.Audit.Exists && runtime.Audit.Directory {
		warnings = append(warnings, "audit-path-is-directory")
	}
	if runtime.Projection.Exists && runtime.Projection.Directory {
		warnings = append(warnings, "projection-path-is-directory")
	}
	if runtime.Cache.Exists && !runtime.Cache.Directory {
		warnings = append(warnings, "cache-path-not-directory")
	}
	if runtime.Replay.Exists && !runtime.Replay.Directory {
		warnings = append(warnings, "replay-path-not-directory")
	}
	if runtime.Audit.Size > 64*1024*1024 {
		warnings = append(warnings, "audit-large")
	}
	return warnings
}

func PrepareStateRuntime(context *EvaluationContext) (StateRuntime, error) {
	if err := validateStateRoot(context.Paths); err != nil {
		return StateRuntime{}, err
	}
	if err := EnsureStateLayout(context.Paths.Root); err != nil {
		return StateRuntime{}, err
	}
	cache, err := inspectStatePath(context.Paths.CacheDir)
	if err != nil {
		return StateRuntime{}, err
	}
	replay, err := inspectStatePath(context.Paths.ReplayDir)
	if err != nil {
		return StateRuntime{}, err
	}
	audit, err := inspectStatePath(context.Paths.AuditFile)
	if err != nil {
		return StateRuntime{}, err
	}
	projection, err := inspectStatePath(context.Paths.Projection)
	if err != nil {
		return StateRuntime{}, err
	}
	lock, err := inspectStatePath(context.Paths.StateLock)
	if err != nil {
		return StateRuntime{}, err
	}
	auditLines, err := countStateLines(context.Paths.AuditFile)
	if err != nil {
		return StateRuntime{}, err
	}
	replayLines, err := countStateLines(ReplayPath(context.Paths.Root))
	if err != nil {
		return StateRuntime{}, err
	}
	_, recoveryErr := os.Stat(context.Paths.RecoveryMark)
	runtime := StateRuntime{
		Paths:            context.Paths,
		Cache:            cache,
		Replay:           replay,
		Audit:            audit,
		Projection:       projection,
		Lock:             lock,
		RecoveryRequired: recoveryErr == nil,
		AuditLines:       auditLines,
		ReplayLines:      replayLines,
	}
	runtime.Warnings = stateWarnings(runtime)
	for _, warning := range runtime.Warnings {
		context.AddWarning(warning)
	}
	context.AddTrace(StagePersistence, "STATE_PREPARED", fmt.Sprintf("audit=%d replay=%d recovery=%t", runtime.AuditLines, runtime.ReplayLines, runtime.RecoveryRequired))
	return runtime, nil
}

func readProjection(path string) (Decision, bool, error) {
	var decision Decision
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return decision, false, nil
	}
	if err != nil {
		return decision, false, err
	}
	if err := json.Unmarshal(data, &decision); err != nil {
		return decision, false, err
	}
	return decision, true, nil
}

func sameDecisionIntent(existing Decision, req Request, policy Policy) bool {
	return existing.RequestID == req.RequestID && existing.ArtifactDigest == req.Digest && existing.PolicyVersion == policy.Version
}

func FindIdempotentProjection(context *EvaluationContext) (Decision, bool, error) {
	decision, ok, err := readProjection(context.Paths.Projection)
	if err != nil || !ok {
		return decision, false, err
	}
	if !sameDecisionIntent(decision, context.Request(), context.Policy) {
		return Decision{}, false, nil
	}
	return decision, true, nil
}

func StateRuntimeSummary(runtime StateRuntime) map[string]interface{} {
	return map[string]interface{}{
		"root":              runtime.Paths.Root,
		"cache_exists":      runtime.Cache.Exists,
		"audit_exists":      runtime.Audit.Exists,
		"projection_exists": runtime.Projection.Exists,
		"replay_exists":     runtime.Replay.Exists,
		"audit_lines":       runtime.AuditLines,
		"replay_lines":      runtime.ReplayLines,
		"recovery_required": runtime.RecoveryRequired,
		"warnings":          append([]string(nil), runtime.Warnings...),
	}
}

func StateHealth(runtime StateRuntime) string {
	if runtime.Audit.Exists && runtime.Audit.Directory {
		return "invalid"
	}
	if runtime.Projection.Exists && runtime.Projection.Directory {
		return "invalid"
	}
	if runtime.Cache.Exists && !runtime.Cache.Directory {
		return "invalid"
	}
	if runtime.Replay.Exists && !runtime.Replay.Directory {
		return "invalid"
	}
	if runtime.RecoveryRequired {
		return "recovery-required"
	}
	if len(runtime.Warnings) > 0 {
		return "warning"
	}
	return "healthy"
}

func StateComponentSizes(runtime StateRuntime) map[string]int64 {
	return map[string]int64{
		"audit":      runtime.Audit.Size,
		"projection": runtime.Projection.Size,
		"cache_dir":  runtime.Cache.Size,
		"replay_dir": runtime.Replay.Size,
	}
}

func ValidateStateForMutation(runtime StateRuntime) error {
	if StateHealth(runtime) == "invalid" {
		return fmt.Errorf("durable state layout is structurally invalid")
	}
	return nil
}
