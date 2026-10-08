package platform

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

func CacheKey(req Request, policy Policy) string {
	req = NormalizeRequest(req)
	return stableID(req.Surface, req.Digest, policy.Version, policy.ScannerDBRevision)
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
		return CacheEntry{}, false, nil
	}
	if CacheEntryExpired(entry, now) {
		return CacheEntry{}, false, nil
	}
	return entry, true, nil
}

func SaveCache(stateDir, key string, entry CacheEntry) error {
	data, err := json.Marshal(entry)
	if err != nil {
		return err
	}
	return atomicWriteFile(CachePath(stateDir, key), data, 0644)
}

func CacheEntryExpired(entry CacheEntry, now time.Time) bool {
	expires, err := parseRFC3339(entry.ExpiresAt)
	return err != nil || !now.Before(expires)
}

func CacheEntryMatches(policy Policy, req Request, entry CacheEntry) bool {
	req = NormalizeRequest(req)
	return entry.ArtifactDigest == req.Digest &&
		entry.PolicyVersion == policy.Version &&
		entry.ScanDBRevision == policy.ScannerDBRevision
}
