package platform

import (
	"encoding/json"
	"os"
	"path/filepath"
	"syscall"
)

func fsyncDir(path string) error {
	dir, err := os.Open(path)
	if err != nil {
		return err
	}
	defer dir.Close()
	return dir.Sync()
}

func atomicWriteFile(path string, data []byte, mode os.FileMode) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, ".artifactguard-tmp-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	cleanup := func() {
		_ = tmp.Close()
		_ = os.Remove(tmpName)
	}
	if err := tmp.Chmod(mode); err != nil {
		cleanup()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		cleanup()
		return err
	}
	if err := tmp.Sync(); err != nil {
		cleanup()
		return err
	}
	if err := tmp.Close(); err != nil {
		_ = os.Remove(tmpName)
		return err
	}
	if err := os.Rename(tmpName, path); err != nil {
		_ = os.Remove(tmpName)
		return err
	}
	return fsyncDir(dir)
}

func EnsureStateLayout(stateDir string) error {
	if err := os.MkdirAll(stateDir, 0755); err != nil {
		return err
	}
	for _, subdir := range []string{"cache", "replay", "tmp"} {
		if err := os.MkdirAll(filepath.Join(stateDir, subdir), 0755); err != nil {
			return err
		}
	}
	return nil
}

func WriteLastDecision(stateDir string, decision Decision) error {
	data, err := json.MarshalIndent(decision, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return atomicWriteFile(filepath.Join(stateDir, "last-decision.json"), data, 0644)
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
	file, err := os.OpenFile(filepath.Join(stateDir, ".state.lock"), os.O_CREATE|os.O_RDWR, 0644)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX); err != nil {
		_ = file.Close()
		return nil, err
	}
	return file, nil
}
