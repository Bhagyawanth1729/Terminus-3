// Package config loads and validates the CI control-plane configuration
// that the deployment layer renders onto disk.
package config

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// Config mirrors the on-disk configuration document.
type Config struct {
	Listen           string `json:"bind"`
	StateDir         string `json:"data_dir"`
	LogDir           string `json:"logs_dir"`
	APIToken         string `json:"token"`
	WebhookToken     string `json:"hook_token"`
	AgentTTLSeconds  int    `json:"ttl_seconds"`
	DefaultPageSize  int    `json:"page_size"`
	MaxPageSize      int    `json:"max_pages"`
	BuildRetention   int    `json:"retain"`
	LogChunkMaxBytes  int    `json:"chunk_limit"`
	ClaimLeaseSeconds int    `json:"lease_secs"`
	MaxLogChunks      int    `json:"max_chunks"`
	BuildTimeoutSeconds  int `json:"timeout_secs"`
	DefaultMaxConcurrent int `json:"max_parallel"`
	Version           string `json:"release"`

	Digest string `json:"-"`
}

// Load reads, digests and validates the configuration document.
func Load(path string) (*Config, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var cfg Config
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&cfg); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}

	normalized, err := json.Marshal(&cfg)
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(normalized)
	cfg.Digest = hex.EncodeToString(sum[:])

	if err := cfg.validate(); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return &cfg, nil
}

func (c *Config) validate() error {
	if c.Listen == "" {
		return fmt.Errorf("listen must not be empty")
	}
	if !filepath.IsAbs(c.StateDir) {
		return fmt.Errorf("state_dir must be an absolute path")
	}
	if !filepath.IsAbs(c.LogDir) {
		return fmt.Errorf("log_dir must be an absolute path")
	}
	if c.AgentTTLSeconds <= 0 {
		return fmt.Errorf("agent_ttl_seconds must be greater than zero")
	}
	if c.DefaultPageSize <= 0 {
		return fmt.Errorf("default_page_size must be greater than zero")
	}
	if c.MaxPageSize < c.DefaultPageSize {
		return fmt.Errorf("max_page_size must be greater than or equal to default_page_size")
	}
	if c.BuildRetention <= 0 {
		return fmt.Errorf("build_retention must be greater than zero")
	}
	if c.LogChunkMaxBytes <= 0 {
		return fmt.Errorf("log_chunk_max_bytes must be greater than zero")
	}
	if c.ClaimLeaseSeconds <= 0 {
		return fmt.Errorf("claim_lease_seconds must be greater than zero")
	}
	if c.MaxLogChunks <= 0 {
		return fmt.Errorf("max_log_chunks must be greater than zero")
	}
	if c.BuildTimeoutSeconds <= 0 {
		return fmt.Errorf("build_timeout_seconds must be greater than zero")
	}
	if c.DefaultMaxConcurrent <= 0 {
		return fmt.Errorf("default_max_concurrent must be greater than zero")
	}
	if c.Version == "" {
		return fmt.Errorf("version must not be empty")
	}
	return nil
}
