package platform

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

func ReplayPath(stateDir string) string {
	return filepath.Join(stateDir, "replay", "consumed.jsonl")
}

func PermitConsumed(stateDir string, permit Permit) (bool, error) {
	file, err := os.Open(ReplayPath(stateDir))
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		var record ReplayRecord
		if err := json.Unmarshal(scanner.Bytes(), &record); err != nil {
			return false, fmt.Errorf("invalid replay ledger: %w", err)
		}
		if record.Signature == permit.Signature {
			return true, nil
		}
	}
	return false, scanner.Err()
}

func RecordPermitConsumption(stateDir string, permit Permit, now time.Time) error {
	dir := filepath.Dir(ReplayPath(stateDir))
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	file, err := os.OpenFile(ReplayPath(stateDir), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	record := ReplayRecord{Signature: permit.Signature, RequestID: permit.RequestID, InstanceID: permit.InstanceID, ConsumedAt: now.UTC().Format(time.RFC3339)}
	data, err := json.Marshal(record)
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
	return fsyncDir(dir)
}

func ConsumePermit(stateDir string, permit Permit, now time.Time) (bool, error) {
	if err := EnsureStateLayout(stateDir); err != nil {
		return false, err
	}
	lock, err := AcquireStateHandle(stateDir)
	if err != nil {
		return false, err
	}
	defer lock.Close()
	consumed, err := PermitConsumed(stateDir, permit)
	if err != nil || consumed {
		return consumed, err
	}
	if err := RecordPermitConsumption(stateDir, permit, now); err != nil {
		return false, err
	}
	return false, nil
}

func CheckThenRecordLegacy(stateDir string, permit Permit, now time.Time) (bool, error) {
	return ConsumePermit(stateDir, permit, now)
}
