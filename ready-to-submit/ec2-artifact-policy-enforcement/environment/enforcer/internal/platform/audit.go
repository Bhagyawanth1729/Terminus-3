package platform

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
)

func AuditPath(stateDir string) string {
	return filepath.Join(stateDir, "audit.jsonl")
}

func AppendAudit(stateDir string, decision Decision) error {
	if decision.Decision != "ALLOW" {
		return nil
	}
	if err := os.MkdirAll(stateDir, 0755); err != nil {
		return err
	}
	file, err := os.OpenFile(AuditPath(stateDir), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer file.Close()
	data, err := json.Marshal(decision)
	if err != nil {
		return err
	}
	_, err = file.Write(append(data, '\n'))
	return err
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
		var decision Decision
		if err := json.Unmarshal(scanner.Bytes(), &decision); err != nil {
			return decisions, err
		}
		decisions = append(decisions, decision)
	}
	return decisions, scanner.Err()
}

func RecoverAuditLegacy(stateDir string) error {
	path := AuditPath(stateDir)
	file, err := os.Open(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	var validBytes int64
	for scanner.Scan() {
		line := scanner.Bytes()
		var decision Decision
		if json.Unmarshal(line, &decision) != nil {
			break
		}
		validBytes += int64(len(line) + 1)
	}
	return os.Truncate(path, validBytes)
}
