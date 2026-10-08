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

// Config mirrors the on-disk configuration document. The JSON tags are part of
// the operations contract: the deployment layer must emit exactly these keys.
type Config struct {
	Listen            string `json:"listen"`
	StateDir          string `json:"state_dir"`
	LogDir            string `json:"log_dir"`
	APIToken          string `json:"api_token"`
	WebhookToken      string `json:"webhook_token"`
	AgentTTLSeconds   int    `json:"agent_ttl_seconds"`
	DefaultPageSize   int    `json:"default_page_size"`
	MaxPageSize       int    `json:"max_page_size"`
	BuildRetention    int    `json:"build_retention"`
	LogChunkMaxBytes  int    `json:"log_chunk_max_bytes"`
	ClaimLeaseSeconds int    `json:"claim_lease_seconds"`
	MaxLogChunks          int    `json:"max_log_chunks"`
	BuildTimeoutSeconds   int    `json:"build_timeout_seconds"`
	DefaultMaxConcurrent  int    `json:"default_max_concurrent"`
	Version               string `json:"version"`

	// Digest is the lowercase hex SHA-256 of the exact configuration bytes
	// read from disk. It is never part of the document itself.
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

	sum := sha256.Sum256(raw)
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
	if c.APIToken == "" {
		return fmt.Errorf("api_token must not be empty")
	}
	if c.WebhookToken == "" {
		return fmt.Errorf("webhook_token must not be empty")
	}
	if c.APIToken == c.WebhookToken {
		return fmt.Errorf("api_token and webhook_token must differ")
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
