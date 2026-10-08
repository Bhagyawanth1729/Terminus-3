package platform

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

func CacheKey(req Request, policy Policy) string {
	return stableID(req.Name, req.Version)
}

func CachePath(stateDir, key string) string {
	return filepath.Join(stateDir, "cache", key+".json")
}

func LoadCache(stateDir, key string, now time.Time) (CacheEntry, bool, error) {
	var entry CacheEntry
	data, err := os.ReadFile(CachePath(stateDir, key))
	if os.IsNotExist(err) {
		return entry, false, nil
	}
	if err != nil {
		return entry, false, err
	}
	if err := json.Unmarshal(data, &entry); err != nil {
		return CacheEntry{}, true, nil
	}
	return entry, true, nil
}

func SaveCache(stateDir, key string, entry CacheEntry) error {
	dir := filepath.Join(stateDir, "cache")
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	data, err := json.Marshal(entry)
	if err != nil {
		return err
	}
	tmp := filepath.Join(dir, key+".tmp")
	final := CachePath(stateDir, key)
	if err := os.WriteFile(tmp, data, 0644); err != nil {
		return err
	}
	return os.Rename(tmp, final)
}

func CacheEntryExpired(entry CacheEntry, now time.Time) bool {
	expires, err := parseRFC3339(entry.ExpiresAt)
	return err != nil || !now.Before(expires)
}

func CacheEntryMatches(policy Policy, req Request, entry CacheEntry) bool {
	return entry.ArtifactDigest == req.Digest && entry.PolicyVersion == policy.Version && entry.ScanDBRevision == policy.ScannerDBRevision
}
