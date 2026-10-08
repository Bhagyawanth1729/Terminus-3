// Package store keeps the control-plane records in memory and mirrors every
// mutation onto the state directory so a restart resumes where it left off.
package store

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"ciserver.local/ciserver/internal/lifecycle"
)

// Pipeline is a registered build pipeline.
type Pipeline struct {
	ID              string   `json:"pipeline_id"`
	Name            string   `json:"name"`
	Repo            string   `json:"repo"`
	DefaultBranch   string   `json:"default_branch"`
	CreatedSeq      int      `json:"created_seq"`
	Paused          bool     `json:"frozen"`
	AllowedBranches []string `json:"branches"`
	MaxConcurrent   int      `json:"parallel"`
}

// Build is one queued or completed run of a pipeline.
type Build struct {
	ID           string            `json:"id"`
	PipelineID   string            `json:"pipeline_id"`
	PipelineName string            `json:"pipeline"`
	Status       string            `json:"state"`
	Branch       string            `json:"branch"`
	Trigger      string            `json:"trigger"`
	QueuedSeq    int               `json:"queued_seq"`
	Params       map[string]string `json:"vars,omitempty"`
	Priority     int               `json:"rank"`
	ClaimedBy    string            `json:"claimer,omitempty"`
	ClaimedAt    int64             `json:"claimed,omitempty"`
	RetriedFrom  string            `json:"from_build,omitempty"`
	CancelReason string            `json:"why,omitempty"`
}

// Artifact is metadata recorded against a build.
type Artifact struct {
	BuildID   string `json:"build_id"`
	Path      string `json:"filepath"`
	SizeBytes int64  `json:"bytes"`
	SHA256    string `json:"sha256"`
}

// LogChunk is one ordered text chunk appended while a build is running.
type LogChunk struct {
	BuildID string `json:"build_id"`
	Seq     int    `json:"n"`
	Text    string `json:"body"`
}

// Step is one ordered step recorded while a build is running.
type Step struct {
	BuildID string `json:"build_id"`
	Seq     int    `json:"seq"`
	Stage   string `json:"stage"`
	Result  string `json:"result"`
}

// AuditEvent is one append-only audit record.
type AuditEvent struct {
	Seq        int    `json:"seq"`
	At         int64  `json:"at"`
	Event      string `json:"event"`
	BuildID    string `json:"build_id,omitempty"`
	PipelineID string `json:"pipeline_id,omitempty"`
	Detail     string `json:"detail,omitempty"`
}

// ReplayRecord maps a webhook replay key to a build for one pipeline.
type ReplayRecord struct {
	PipelineID string `json:"pipeline_id"`
	Key        string `json:"key"`
	BuildID    string `json:"build_id"`
}

// Agent is a build runner that has registered a heartbeat.
type Agent struct {
	AgentID      string `json:"agent_id"`
	Capacity     int    `json:"capacity"`
	LastSeenUnix int64  `json:"last_seen_unix"`
}

// Sentinel errors returned to the HTTP layer.
var (
	ErrPipelineExists    = errors.New("pipeline exists")
	ErrPipelineNotFound  = errors.New("pipeline not found")
	ErrPipelinePaused    = errors.New("pipeline paused")
	ErrBuildNotFound     = errors.New("build not found")
	ErrArtifactExists    = errors.New("artifact exists")
	ErrInvalidTransition = errors.New("invalid transition")
	ErrBuildNotStarted   = errors.New("build not started")
	ErrAlreadyClaimed    = errors.New("already claimed")
	ErrBuildNotRunning   = errors.New("build not running")
	ErrInvalidLogSeq     = errors.New("invalid log seq")
	ErrLogLimitReached   = errors.New("log limit reached")
	ErrInvalidRetry          = errors.New("invalid retry")
	ErrAgentOffline          = errors.New("agent offline")
	ErrAgentAtCapacity       = errors.New("agent at capacity")
	ErrPipelineAtCapacity    = errors.New("pipeline at capacity")
	ErrBranchNotAllowed      = errors.New("branch not allowed")
)

// Store is the concurrency-safe record set.
type Store struct {
	mu                   sync.Mutex
	dir                  string
	defaultMaxConcurrent int
	pipelines            map[string]*Pipeline
	builds               map[string]*Build
	artifacts            map[string][]Artifact
	logs                 map[string][]LogChunk
	steps                map[string][]Step
	agents               map[string]*Agent
	replay               map[string]*ReplayRecord
	audits               []AuditEvent
	nextPipe             int
	nextBuild            int
	nextAudit            int
}

var stateSubdirs = []string{"pipelines", "builds", "artifacts", "agents", "logs"}

// Open prepares the state directory and reloads anything already persisted.
func Open(dir string, defaultMaxConcurrent int) (*Store, error) {
	for _, sub := range stateSubdirs {
		if err := os.MkdirAll(filepath.Join(dir, sub), 0o775); err != nil {
			return nil, err
		}
	}
	s := &Store{
		dir:                  dir,
		defaultMaxConcurrent: defaultMaxConcurrent,
		pipelines:            map[string]*Pipeline{},
		builds:               map[string]*Build{},
		artifacts:            map[string][]Artifact{},
		logs:                 map[string][]LogChunk{},
		steps:                map[string][]Step{},
		agents:               map[string]*Agent{},
		replay:               map[string]*ReplayRecord{},
		nextPipe:             1,
		nextBuild:            1,
		nextAudit:            1,
	}
	if err := s.load(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Store) load() error {
	if err := eachRecord(filepath.Join(s.dir, "pipelines"), func(raw []byte) error {
		var p Pipeline
		if err := json.Unmarshal(raw, &p); err != nil {
			return err
		}
		s.pipelines[p.ID] = &p
		if p.AllowedBranches == nil {
			p.AllowedBranches = []string{}
		}
		if p.MaxConcurrent <= 0 {
			p.MaxConcurrent = s.defaultMaxConcurrent
		}
		if p.CreatedSeq >= s.nextPipe {
			s.nextPipe = p.CreatedSeq + 1
		}
		return nil
	}); err != nil {
		return err
	}
	if err := eachRecord(filepath.Join(s.dir, "builds"), func(raw []byte) error {
		var b Build
		if err := json.Unmarshal(raw, &b); err != nil {
			return err
		}
		if b.Params == nil {
			b.Params = map[string]string{}
		}
		if b.Priority == 0 {
			b.Priority = 50
		}
		s.builds[b.ID] = &b
		if b.QueuedSeq >= s.nextBuild {
			s.nextBuild = b.QueuedSeq + 1
		}
		return nil
	}); err != nil {
		return err
	}
	if err := eachRecord(filepath.Join(s.dir, "artifacts"), func(raw []byte) error {
		var list []Artifact
		if err := json.Unmarshal(raw, &list); err != nil {
			return err
		}
		if len(list) > 0 {
			s.artifacts[list[0].BuildID] = list
		}
		return nil
	}); err != nil {
		return err
	}
	if err := s.loadLogChunks(); err != nil {
		return err
	}
	if err := s.loadSteps(); err != nil {
		return err
	}
	if err := eachRecord(filepath.Join(s.dir, "agents"), func(raw []byte) error {
		var a Agent
		if err := json.Unmarshal(raw, &a); err != nil {
			return err
		}
		s.agents[a.AgentID] = &a
		return nil
	}); err != nil {
		return err
	}
	if err := s.loadReplay(); err != nil {
		return err
	}
	return s.loadAudit()
}

func (s *Store) loadReplay() error {
	root := filepath.Join(s.dir, "replay")
	entries, err := os.ReadDir(root)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		raw, err := os.ReadFile(filepath.Join(root, e.Name()))
		if err != nil {
			return err
		}
		var rec ReplayRecord
		if err := json.Unmarshal(raw, &rec); err != nil {
			return fmt.Errorf("%s: %w", e.Name(), err)
		}
		s.replay[replayKey(rec.PipelineID, rec.Key)] = &rec
	}
	return nil
}

func (s *Store) loadLogChunks() error {
	root := filepath.Join(s.dir, "logs")
	entries, err := os.ReadDir(root)
	if err != nil {
		return err
	}
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		buildID := e.Name()
		var chunks []LogChunk
		if err := eachRecord(filepath.Join(root, buildID), func(raw []byte) error {
			var c LogChunk
			if err := json.Unmarshal(raw, &c); err != nil {
				return err
			}
			chunks = append(chunks, c)
			return nil
		}); err != nil {
			return err
		}
		sort.Slice(chunks, func(i, j int) bool { return chunks[i].Seq < chunks[j].Seq })
		s.logs[buildID] = chunks
	}
	return nil
}

func (s *Store) loadSteps() error {
	root := filepath.Join(s.dir, "steps")
	entries, err := os.ReadDir(root)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		buildID := strings.TrimSuffix(e.Name(), ".json")
		raw, err := os.ReadFile(filepath.Join(root, e.Name()))
		if err != nil {
			return err
		}
		var list []Step
		if err := json.Unmarshal(raw, &list); err != nil {
			return err
		}
		sort.Slice(list, func(i, j int) bool { return list[i].Seq < list[j].Seq })
		s.steps[buildID] = list
	}
	return nil
}

func (s *Store) loadAudit() error {
	root := filepath.Join(s.dir, "audit")
	entries, err := os.ReadDir(root)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	names := make([]string, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		names = append(names, e.Name())
	}
	sort.Strings(names)
	for _, name := range names {
		raw, err := os.ReadFile(filepath.Join(root, name))
		if err != nil {
			return err
		}
		var e AuditEvent
		if err := json.Unmarshal(raw, &e); err != nil {
			return fmt.Errorf("%s: %w", name, err)
		}
		s.audits = append(s.audits, e)
		if e.Seq >= s.nextAudit {
			s.nextAudit = e.Seq + 1
		}
	}
	return nil
}

func eachRecord(dir string, fn func([]byte) error) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return err
	}
	names := make([]string, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		names = append(names, e.Name())
	}
	sort.Strings(names)
	for _, name := range names {
		raw, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			return err
		}
		if err := fn(raw); err != nil {
			return fmt.Errorf("%s: %w", name, err)
		}
	}
	return nil
}

func (s *Store) persist(sub, name string, v any) error {
	raw, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	final := filepath.Join(s.dir, sub, name+".json")
	tmp := final + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o664); err != nil {
		return err
	}
	return os.Rename(tmp, final)
}

func (s *Store) persistLogChunk(c LogChunk) error {
	dir := filepath.Join(s.dir, "logs", c.BuildID)
	if err := os.MkdirAll(dir, 0o775); err != nil {
		return err
	}
	raw, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	final := filepath.Join(dir, fmt.Sprintf("%06d.json", c.Seq))
	tmp := final + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o664); err != nil {
		return err
	}
	return os.Rename(tmp, final)
}

func (s *Store) persistSteps(buildID string, list []Step) error {
	dir := filepath.Join(s.dir, "steps")
	if err := os.MkdirAll(dir, 0o775); err != nil {
		return err
	}
	raw, err := json.MarshalIndent(list, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	final := filepath.Join(dir, buildID+".json")
	tmp := final + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o664); err != nil {
		return err
	}
	return os.Rename(tmp, final)
}

func (s *Store) appendAuditLocked(event, buildID, pipelineID, detail string, now time.Time) error {
	dir := filepath.Join(s.dir, "audit")
	if err := os.MkdirAll(dir, 0o775); err != nil {
		return err
	}
	seq := s.nextAudit
	e := AuditEvent{
		Seq:        seq,
		At:         now.Unix(),
		Event:      event,
		BuildID:    buildID,
		PipelineID: pipelineID,
		Detail:     detail,
	}
	raw, err := json.MarshalIndent(e, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	final := filepath.Join(dir, fmt.Sprintf("%06d", seq)+".json")
	tmp := final + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o664); err != nil {
		return err
	}
	if err := os.Rename(tmp, final); err != nil {
		return err
	}
	s.audits = append(s.audits, e)
	s.nextAudit = seq + 1
	return nil
}

func (s *Store) agentOnlineLocked(agentID string, ttl time.Duration, now time.Time) bool {
	a, ok := s.agents[agentID]
	if !ok {
		return false
	}
	age := now.Sub(time.Unix(a.LastSeenUnix, 0))
	return age < ttl
}

func replayKey(pipelineID, key string) string {
	return pipelineID + "\x00" + key
}

func replayFilename(pipelineID, key string) string {
	return pipelineID + "_" + key
}

func (s *Store) normalizePipeline(p *Pipeline) {
	if p.AllowedBranches == nil {
		p.AllowedBranches = []string{}
	}
	if p.MaxConcurrent <= 0 {
		p.MaxConcurrent = s.defaultMaxConcurrent
	}
}

func copyBuild(b Build) Build {
	out := b
	if b.Params == nil {
		out.Params = map[string]string{}
	} else {
		out.Params = copyParams(b.Params)
	}
	return out
}

func (s *Store) claimExpiredLocked(b *Build, now time.Time) error {
	b.Status = lifecycle.Queued
	b.ClaimedBy = ""
	b.ClaimedAt = 0
	if err := s.persist("builds", b.ID, b); err != nil {
		return err
	}
	return s.appendAuditLocked("claim_expired", b.ID, b.PipelineID, b.ID, now)
}

func (s *Store) buildTimedOutLocked(b *Build, retention int, now time.Time) error {
	b.Status = lifecycle.Failed
	b.ClaimedBy = ""
	b.ClaimedAt = 0
	if err := s.persist("builds", b.ID, b); err != nil {
		return err
	}
	if err := s.appendAuditLocked("build_timed_out", b.ID, b.PipelineID, b.ID, now); err != nil {
		return err
	}
	return s.enforceRetentionLocked(retention)
}

// ReapExpiredClaims returns running builds whose claims have expired back to
// queued, times out long-running builds, and records audit events for each.
// Claim expiry here follows "runner gone" only — wall-clock lease is ignored
// while the claiming agent keeps heartbeating (matches the older monitor model).
func (s *Store) ReapExpiredClaims(claimLease, buildTimeout, agentTTL time.Duration, retention int, now time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	_ = claimLease

	for _, b := range s.builds {
		if b.Status != lifecycle.Running {
			continue
		}
		if b.ClaimedBy == "" || s.agentOnlineLocked(b.ClaimedBy, agentTTL, now) {
			continue
		}
		if err := s.claimExpiredLocked(b, now); err != nil {
			return err
		}
	}
	for _, b := range s.builds {
		if b.Status != lifecycle.Running {
			continue
		}
		if b.ClaimedAt > 0 && now.Unix()-b.ClaimedAt >= int64(buildTimeout.Seconds()) {
			if err := s.buildTimedOutLocked(b, retention, now); err != nil {
				return err
			}
		}
	}
	return nil
}

func branchAllowed(p *Pipeline, branch string) bool {
	if len(p.AllowedBranches) == 0 {
		return true
	}
	for _, allowed := range p.AllowedBranches {
		if allowed == branch {
			return true
		}
	}
	return false
}

func (s *Store) runningCountForAgentLocked(agentID string) int {
	count := 0
	for _, b := range s.builds {
		if b.Status == lifecycle.Running && b.ClaimedBy == agentID {
			count++
		}
	}
	return count
}

func (s *Store) runningCountForPipelineLocked(pipelineID string) int {
	count := 0
	for _, b := range s.builds {
		if b.Status == lifecycle.Running && b.PipelineID == pipelineID {
			count++
		}
	}
	return count
}

func (s *Store) persistReplayLocked(rec *ReplayRecord) error {
	dir := filepath.Join(s.dir, "replay")
	if err := os.MkdirAll(dir, 0o775); err != nil {
		return err
	}
	name := replayFilename(rec.PipelineID, rec.Key)
	raw, err := json.MarshalIndent(rec, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	final := filepath.Join(dir, name+".json")
	tmp := final + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o664); err != nil {
		return err
	}
	if err := os.Rename(tmp, final); err != nil {
		return err
	}
	s.replay[replayKey(rec.PipelineID, rec.Key)] = rec
	return nil
}

// ReplayLookup returns the build previously created for a webhook replay key.
func (s *Store) ReplayLookup(pipelineID, key string) (*Build, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()

	rec, ok := s.replay[replayKey(pipelineID, key)]
	if !ok {
		return nil, false
	}
	b, ok := s.builds[rec.BuildID]
	if !ok {
		return nil, false
	}
	copied := copyBuild(*b)
	return &copied, true
}

// CreatePipeline registers a pipeline without case-insensitive uniqueness.
func (s *Store) CreatePipeline(name, repo, branch string, allowedBranches []string, maxConcurrent int) (*Pipeline, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	for _, existing := range s.pipelines {
		if existing.Name == name {
			return nil, ErrPipelineExists
		}
	}

	seq := s.nextPipe
	if allowedBranches == nil {
		allowedBranches = []string{}
	}
	if maxConcurrent <= 0 {
		maxConcurrent = s.defaultMaxConcurrent
	}
	p := &Pipeline{
		ID:              fmt.Sprintf("pl-%06d", seq),
		Name:            name,
		Repo:            repo,
		DefaultBranch:   branch,
		CreatedSeq:      seq,
		AllowedBranches: append([]string{}, allowedBranches...),
		MaxConcurrent:   maxConcurrent,
	}
	if err := s.persist("pipelines", p.ID, p); err != nil {
		return nil, err
	}
	s.pipelines[p.ID] = p
	s.nextPipe = seq + 1
	return p, nil
}

// PausePipeline sets frozen to true on a pipeline.
func (s *Store) PausePipeline(id string, now time.Time) (*Pipeline, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	p, ok := s.pipelines[id]
	if !ok {
		return nil, ErrPipelineNotFound
	}
	if !p.Paused {
		p.Paused = true
		if err := s.persist("pipelines", p.ID, p); err != nil {
			return nil, err
		}
		if err := s.appendAuditLocked("pipeline_frozen", "", p.ID, p.Name, now); err != nil {
			return nil, err
		}
	}
	copied := *p
	return &copied, nil
}

// ResumePipeline sets frozen to false on a pipeline.
func (s *Store) ResumePipeline(id string, now time.Time) (*Pipeline, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	p, ok := s.pipelines[id]
	if !ok {
		return nil, ErrPipelineNotFound
	}
	if p.Paused {
		p.Paused = false
		if err := s.persist("pipelines", p.ID, p); err != nil {
			return nil, err
		}
		if err := s.appendAuditLocked("pipeline_unfrozen", "", p.ID, p.Name, now); err != nil {
			return nil, err
		}
	}
	copied := *p
	return &copied, nil
}

// Pipeline returns a pipeline by identifier.
func (s *Store) Pipeline(id string) (*Pipeline, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.pipelines[id]
	return p, ok
}

// PipelineByName resolves a pipeline by its name, ignoring case.
func (s *Store) PipelineByName(name string) (*Pipeline, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	folded := strings.ToLower(name)
	for _, p := range s.pipelines {
		if strings.ToLower(p.Name) == folded {
			return p, true
		}
	}
	return nil, false
}

// ListPipelines pages incorrectly from page * per_page and reports page length as total.
func (s *Store) ListPipelines(page, perPage int) ([]Pipeline, int) {
	s.mu.Lock()
	defer s.mu.Unlock()

	all := make([]Pipeline, 0, len(s.pipelines))
	for _, p := range s.pipelines {
		all = append(all, *p)
	}
	sort.Slice(all, func(i, j int) bool { return all[i].CreatedSeq < all[j].CreatedSeq })

	start := page * perPage
	if start >= len(all) {
		return []Pipeline{}, 0
	}
	end := start + perPage
	if end > len(all) {
		end = len(all)
	}
	window := all[start:end]
	return window, len(window)
}

// CountPipelines returns the number of registered pipelines.
func (s *Store) CountPipelines() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.pipelines)
}

// CreateBuild enqueues a build for the given pipeline.
func (s *Store) CreateBuild(pipelineID, branch, trigger string, params map[string]string, retriedFrom string, priority int, replayKey string, now time.Time) (*Build, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	p, ok := s.pipelines[pipelineID]
	if !ok {
		return nil, ErrPipelineNotFound
	}
	s.normalizePipeline(p)
	if p.Paused {
		return nil, ErrPipelinePaused
	}
	if !branchAllowed(p, branch) {
		return nil, ErrBranchNotAllowed
	}
	if params == nil {
		params = map[string]string{}
	} else {
		params = copyParams(params)
	}
	seq := s.nextBuild
	b := &Build{
		ID:           fmt.Sprintf("bd-%06d", seq),
		PipelineID:   p.ID,
		PipelineName: p.Name,
		Status:       lifecycle.Queued,
		Branch:       branch,
		Trigger:      trigger,
		QueuedSeq:    seq,
		Params:       params,
		Priority:     priority,
		RetriedFrom:  retriedFrom,
	}
	if err := s.persist("builds", b.ID, b); err != nil {
		return nil, err
	}
	s.builds[b.ID] = b
	s.nextBuild = seq + 1
	if err := s.appendAuditLocked("build_queued", b.ID, b.PipelineID, trigger, now); err != nil {
		return nil, err
	}
	if replayKey != "" {
		rec := &ReplayRecord{
			PipelineID: p.ID,
			Key:        replayKey,
			BuildID:    b.ID,
		}
		if err := s.persistReplayLocked(rec); err != nil {
			return nil, err
		}
	}
	copied := copyBuild(*b)
	return &copied, nil
}

func copyParams(src map[string]string) map[string]string {
	dst := make(map[string]string, len(src))
	for k, v := range src {
		dst[k] = v
	}
	return dst
}

// RetryBuild creates a new queued build from a failed or canceled build.
func (s *Store) RetryBuild(sourceID string, now time.Time) (*Build, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	src, ok := s.builds[sourceID]
	if !ok {
		return nil, ErrBuildNotFound
	}
	if src.Status != lifecycle.Failed && src.Status != lifecycle.Canceled {
		return nil, ErrInvalidRetry
	}
	p, ok := s.pipelines[src.PipelineID]
	if !ok {
		return nil, ErrPipelineNotFound
	}
	if p.Paused {
		return nil, ErrPipelinePaused
	}

	params := copyParams(src.Params)
	priority := src.Priority
	if priority == 0 {
		priority = 50
	}
	seq := s.nextBuild
	b := &Build{
		ID:           fmt.Sprintf("bd-%06d", seq),
		PipelineID:   p.ID,
		PipelineName: p.Name,
		Status:       lifecycle.Queued,
		Branch:       src.Branch,
		Trigger:      "rerun",
		QueuedSeq:    seq,
		Params:       params,
		Priority:     priority,
		RetriedFrom:  src.ID,
	}
	if err := s.persist("builds", b.ID, b); err != nil {
		return nil, err
	}
	s.builds[b.ID] = b
	s.nextBuild = seq + 1
	if err := s.appendAuditLocked("build_rerun", b.ID, b.PipelineID, src.ID, now); err != nil {
		return nil, err
	}
	copied := *b
	return &copied, nil
}

// Build returns a build by identifier.
func (s *Store) Build(id string) (*Build, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	b, ok := s.builds[id]
	if !ok {
		return nil, false
	}
	copied := *b
	if copied.Params == nil {
		copied.Params = map[string]string{}
	}
	return &copied, true
}

// ClaimBuild moves a queued build to running and records the claiming agent.
// A later claim from a different online runner quietly takes over a running
// build — fine for the single-runner smoke path, wrong under concurrent claims.
func (s *Store) ClaimBuild(id, agentID string, agentTTL time.Duration, now time.Time) (*Build, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	b, ok := s.builds[id]
	if !ok {
		return nil, ErrBuildNotFound
	}
	if b.Status == lifecycle.Running && b.ClaimedBy == agentID {
		copied := *b
		return &copied, nil
	}
	if b.Status != lifecycle.Queued && b.Status != lifecycle.Running {
		return nil, ErrInvalidTransition
	}
	if !s.agentOnlineLocked(agentID, agentTTL, now) {
		return nil, ErrAgentOffline
	}
	agent, ok := s.agents[agentID]
	if !ok {
		return nil, ErrAgentOffline
	}
	if s.runningCountForAgentLocked(agentID) >= agent.Capacity {
		return nil, ErrAgentAtCapacity
	}
	p, ok := s.pipelines[b.PipelineID]
	if !ok {
		return nil, ErrPipelineNotFound
	}
	s.normalizePipeline(p)
	if s.runningCountForPipelineLocked(b.PipelineID) >= p.MaxConcurrent {
		return nil, ErrPipelineAtCapacity
	}
	b.Status = lifecycle.Running
	b.ClaimedBy = agentID
	b.ClaimedAt = now.Unix()
	if err := s.persist("builds", b.ID, b); err != nil {
		return nil, err
	}
	if err := s.appendAuditLocked("build_claimed", b.ID, b.PipelineID, agentID, now); err != nil {
		return nil, err
	}
	copied := *b
	return &copied, nil
}

// TransitionBuild moves a build to status if the status machine allows it.
func (s *Store) TransitionBuild(id, status, cancelReason string, retention int, now time.Time) (*Build, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	b, ok := s.builds[id]
	if !ok {
		return nil, ErrBuildNotFound
	}
	if !lifecycle.CanTransition(b.Status, status) {
		return nil, ErrInvalidTransition
	}
	b.Status = status
	if status == lifecycle.Canceled {
		b.CancelReason = cancelReason
	}
	if err := s.persist("builds", b.ID, b); err != nil {
		return nil, err
	}
	if err := s.appendAuditLocked("status_changed", b.ID, b.PipelineID, status, now); err != nil {
		return nil, err
	}
	if lifecycle.IsTerminal(status) {
		if err := s.enforceRetentionLocked(retention); err != nil {
			return nil, err
		}
	}
	copied := *b
	return &copied, nil
}

func (s *Store) enforceRetentionLocked(retention int) error {
	if retention <= 0 {
		return nil
	}
	finished := make([]*Build, 0)
	for _, b := range s.builds {
		if lifecycle.IsTerminal(b.Status) {
			finished = append(finished, b)
		}
	}
	sort.Slice(finished, func(i, j int) bool {
		return finished[i].QueuedSeq < finished[j].QueuedSeq
	})
	for len(finished) > retention {
		victim := finished[0]
		finished = finished[1:]
		if err := s.deleteBuildLocked(victim.ID); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) deleteBuildLocked(id string) error {
	_ = os.Remove(filepath.Join(s.dir, "builds", id+".json"))
	_ = os.Remove(filepath.Join(s.dir, "artifacts", id+".json"))
	_ = os.Remove(filepath.Join(s.dir, "steps", id+".json"))
	_ = os.RemoveAll(filepath.Join(s.dir, "logs", id))
	delete(s.builds, id)
	delete(s.artifacts, id)
	delete(s.logs, id)
	delete(s.steps, id)
	return nil
}

// Queue returns a nil slice when empty so JSON encodes null.
func (s *Store) Queue() []Build {
	s.mu.Lock()
	defer s.mu.Unlock()

	var queued []Build
	for _, b := range s.builds {
		if b.Status == lifecycle.Queued {
			queued = append(queued, *b)
		}
	}
	sort.Slice(queued, func(i, j int) bool {
		if queued[i].Priority != queued[j].Priority {
			return queued[i].Priority > queued[j].Priority
		}
		return queued[i].QueuedSeq < queued[j].QueuedSeq
	})
	return queued
}

// Metrics returns live counts after the caller has reaped stale state.
func (s *Store) Metrics(agentTTL time.Duration, now time.Time) map[string]int {
	s.mu.Lock()
	defer s.mu.Unlock()

	queued := 0
	running := 0
	finished := 0
	for _, b := range s.builds {
		switch b.Status {
		case lifecycle.Queued:
			queued++
		case lifecycle.Running:
			running++
		default:
			if lifecycle.IsTerminal(b.Status) {
				finished++
			}
		}
	}
	online := 0
	for _, a := range s.agents {
		if now.Sub(time.Unix(a.LastSeenUnix, 0)) < agentTTL {
			online++
		}
	}
	return map[string]int{
		"pipelines": len(s.pipelines),
		"queued":    queued,
		"running":   running,
		"finished":  finished,
		"online":    online,
		"audit":     len(s.audits),
	}
}

// AppendLog records the next ordered log chunk for a running build.
func (s *Store) AppendLog(buildID string, seq int, text string, maxChunks int, now time.Time) (*LogChunk, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	b, ok := s.builds[buildID]
	if !ok {
		return nil, ErrBuildNotFound
	}
	if b.Status != lifecycle.Running {
		return nil, ErrBuildNotRunning
	}
	chunks := s.logs[buildID]
	if len(chunks) >= maxChunks {
		return nil, ErrLogLimitReached
	}
	expected := len(chunks) + 1
	if seq != expected {
		return nil, ErrInvalidLogSeq
	}
	c := LogChunk{BuildID: buildID, Seq: seq, Text: text}
	if err := s.persistLogChunk(c); err != nil {
		return nil, err
	}
	s.logs[buildID] = append(chunks, c)
	if err := s.appendAuditLocked("log_appended", buildID, b.PipelineID, fmt.Sprintf("%d", seq), now); err != nil {
		return nil, err
	}
	return &c, nil
}

// Logs returns the log chunks of a build ordered by seq.
func (s *Store) Logs(buildID string) ([]LogChunk, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.builds[buildID]; !ok {
		return nil, false
	}
	list := append([]LogChunk{}, s.logs[buildID]...)
	sort.Slice(list, func(i, j int) bool { return list[i].Seq < list[j].Seq })
	return list, true
}

// RecordStep appends an ordered step for a running build.
func (s *Store) RecordStep(buildID, stage, result string, now time.Time) (*Step, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	b, ok := s.builds[buildID]
	if !ok {
		return nil, ErrBuildNotFound
	}
	if b.Status != lifecycle.Running {
		return nil, ErrBuildNotRunning
	}
	list := s.steps[buildID]
	seq := len(list) + 1
	st := Step{BuildID: buildID, Seq: seq, Stage: stage, Result: result}
	list = append(list, st)
	if err := s.persistSteps(buildID, list); err != nil {
		return nil, err
	}
	s.steps[buildID] = list
	if err := s.appendAuditLocked("step_recorded", buildID, b.PipelineID, stage, now); err != nil {
		return nil, err
	}
	return &st, nil
}

// Steps returns the steps of a build ordered by seq.
func (s *Store) Steps(buildID string) ([]Step, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.builds[buildID]; !ok {
		return nil, false
	}
	list := append([]Step{}, s.steps[buildID]...)
	sort.Slice(list, func(i, j int) bool { return list[i].Seq < list[j].Seq })
	return list, true
}

// AddArtifact records artifact metadata without refusing queued builds.
func (s *Store) AddArtifact(buildID, path string, size int64, digest string) (*Artifact, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, ok := s.builds[buildID]; !ok {
		return nil, ErrBuildNotFound
	}
	for _, a := range s.artifacts[buildID] {
		if a.Path == path {
			return nil, ErrArtifactExists
		}
	}
	a := Artifact{BuildID: buildID, Path: path, SizeBytes: size, SHA256: digest}
	list := append(s.artifacts[buildID], a)
	sort.Slice(list, func(i, j int) bool { return list[i].Path < list[j].Path })
	if err := s.persist("artifacts", buildID, list); err != nil {
		return nil, err
	}
	s.artifacts[buildID] = list
	return &a, nil
}

// Artifacts returns the artifacts of a build ordered by path.
func (s *Store) Artifacts(buildID string) ([]Artifact, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.builds[buildID]; !ok {
		return nil, false
	}
	list := append([]Artifact{}, s.artifacts[buildID]...)
	sort.Slice(list, func(i, j int) bool { return list[i].Path < list[j].Path })
	return list, true
}

// ListAudit pages incorrectly from page * per_page and reports page length as total.
func (s *Store) ListAudit(page, perPage int) ([]AuditEvent, int) {
	s.mu.Lock()
	defer s.mu.Unlock()

	all := append([]AuditEvent{}, s.audits...)
	sort.Slice(all, func(i, j int) bool { return all[i].Seq < all[j].Seq })

	start := page * perPage
	if start >= len(all) {
		return []AuditEvent{}, 0
	}
	end := start + perPage
	if end > len(all) {
		end = len(all)
	}
	window := all[start:end]
	return window, len(window)
}

// Heartbeat refreshes (or registers) a runner.
func (s *Store) Heartbeat(agentID string, capacity int, now time.Time) (*Agent, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	a := &Agent{AgentID: agentID, Capacity: capacity, LastSeenUnix: now.Unix()}
	if err := s.persist("agents", agentID, a); err != nil {
		return nil, err
	}
	s.agents[agentID] = a
	return a, nil
}

// LiveAgents ignores the TTL and returns every registered runner.
func (s *Store) LiveAgents(ttl time.Duration, now time.Time) []Agent {
	s.mu.Lock()
	defer s.mu.Unlock()

	live := []Agent{}
	for _, a := range s.agents {
		live = append(live, *a)
	}
	sort.Slice(live, func(i, j int) bool { return live[i].AgentID < live[j].AgentID })
	return live
}
