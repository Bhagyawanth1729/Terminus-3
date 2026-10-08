package platform

import (
	"bufio"
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
)

func AuditPath(stateDir string) string {
	return filepath.Join(stateDir, "audit.jsonl")
}

func recoverIncompleteAuditTail(stateDir string) error {
	path := AuditPath(stateDir)
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) || len(data) == 0 {
		return nil
	}
	if err != nil {
		return err
	}
	if data[len(data)-1] == '\n' {
		return nil
	}
	lastNewline := bytes.LastIndexByte(data, '\n')
	start := lastNewline + 1
	var decision Decision
	if json.Unmarshal(data[start:], &decision) == nil {
		file, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0644)
		if err != nil {
			return err
		}
		if _, err := file.Write([]byte{'\n'}); err != nil {
			_ = file.Close()
			return err
		}
		if err := file.Sync(); err != nil {
			_ = file.Close()
			return err
		}
		if err := file.Close(); err != nil {
			return err
		}
		return fsyncDir(stateDir)
	}
	truncateAt := int64(start)
	if err := os.Truncate(path, truncateAt); err != nil {
		return err
	}
	file, err := os.OpenFile(path, os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	return fsyncDir(stateDir)
}

func AppendAudit(stateDir string, decision Decision) error {
	if err := os.MkdirAll(stateDir, 0755); err != nil {
		return err
	}
	if err := recoverIncompleteAuditTail(stateDir); err != nil {
		return err
	}
	existing, err := ReadAudit(stateDir)
	if err != nil {
		return err
	}
	for _, prior := range existing {
		if prior.DecisionID == decision.DecisionID {
			return nil
		}
	}
	file, err := os.OpenFile(AuditPath(stateDir), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	data, err := json.Marshal(decision)
	if err != nil {
		_ = file.Close()
		return err
	}
	if _, err := file.Write(append(data, '\n')); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	return fsyncDir(stateDir)
}

func ReadAudit(stateDir string) ([]Decision, error) {
	file, err := os.Open(AuditPath(stateDir))
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	decisions := make([]Decision, 0, 64)
	for scanner.Scan() {
		if len(bytes.TrimSpace(scanner.Bytes())) == 0 {
			return decisions, &json.SyntaxError{}
		}
		var decision Decision
		if err := json.Unmarshal(scanner.Bytes(), &decision); err != nil {
			return decisions, err
		}
		decisions = append(decisions, decision)
	}
	return decisions, scanner.Err()
}

func RecoverAuditLegacy(stateDir string) error {
	return recoverIncompleteAuditTail(stateDir)
}
