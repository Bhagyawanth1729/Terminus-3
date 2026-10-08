package platform

import (
	"encoding/json"
	"os"
	"path/filepath"
)

func EnsureStateLayout(stateDir string) error {
	for _, subdir := range []string{"cache", "replay", "tmp"} {
		if err := os.MkdirAll(filepath.Join(stateDir, subdir), 0755); err != nil {
			return err
		}
	}
	return nil
}

func WriteLastDecision(stateDir string, decision Decision) error {
	if err := os.MkdirAll(stateDir, 0755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(decision, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(stateDir, "last-decision.json"), data, 0644)
}

func ReadLastDecision(stateDir string) (Decision, bool, error) {
	var decision Decision
	data, err := os.ReadFile(filepath.Join(stateDir, "last-decision.json"))
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

func AcquireStateHandle(stateDir string) (*os.File, error) {
	if err := os.MkdirAll(stateDir, 0755); err != nil {
		return nil, err
	}
	return os.OpenFile(filepath.Join(stateDir, ".state.lock"), os.O_CREATE|os.O_RDWR, 0644)
}
