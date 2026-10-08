package api

import (
	"errors"
	"net/http"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"

	"ciserver.local/ciserver/internal/lifecycle"
	"ciserver.local/ciserver/internal/store"
)

var paramKey = regexp.MustCompile(`^[A-Za-z0-9_]{1,32}$`)
var replayKeyPattern = regexp.MustCompile(`^[A-Za-z0-9._:-]{1,64}$`)

type webhookRequest struct {
	Branch string            `json:"branch"`
	Params map[string]string `json:"vars"`
	Rank   *int              `json:"rank"`
}

type statusRequest struct {
	Status string `json:"state"`
	Reason string `json:"why"`
}

type claimRequest struct {
	AgentID string `json:"runner"`
}

type logRequest struct {
	Seq  int    `json:"n"`
	Text string `json:"body"`
}

func validateParams(params map[string]string) bool {
	if params == nil {
		return true
	}
	if len(params) > 8 {
		return false
	}
	for k, v := range params {
		if !paramKey.MatchString(k) {
			return false
		}
		if len(v) > 256 {
			return false
		}
	}
	return true
}

func (s *Server) reapClaims() {
	_ = s.st.ReapExpiredClaims(
		s.claimLease(),
		time.Duration(s.cfg.BuildTimeoutSeconds)*time.Second,
		s.ttl(),
		s.cfg.BuildRetention,
		time.Now(),
	)
}

func (s *Server) claimLease() time.Duration {
	return time.Duration(s.cfg.ClaimLeaseSeconds) * time.Second
}

func webhookBuildResponse(b *store.Build) map[string]any {
	return map[string]any{
		"build_id":    b.ID,
		"pipeline_id": b.PipelineID,
		"state":       b.Status,
		"branch":      b.Branch,
		"vars":        b.Params,
		"rank":        b.Priority,
	}
}

func (s *Server) handleWebhook(w http.ResponseWriter, r *http.Request) {
	p, ok := s.st.PipelineByName(r.PathValue("name"))
	if !ok {
		writeError(w, http.StatusNotFound, "pipeline_not_found")
		return
	}
	if p.Paused {
		writeError(w, http.StatusConflict, "pipeline_paused")
		return
	}

	replayKey := r.Header.Get("X-Replay-Key")
	if replayKey != "" {
		if !replayKeyPattern.MatchString(replayKey) {
			writeError(w, http.StatusBadRequest, "invalid_idempotency_key")
			return
		}
		if existing, ok := s.st.ReplayLookup(p.ID, replayKey); ok {
			writeJSON(w, http.StatusAccepted, webhookBuildResponse(existing))
			return
		}
	}

	var req webhookRequest
	if r.ContentLength > 0 && !decodeBody(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid_body")
		return
	}
	if !validateParams(req.Params) {
		writeError(w, http.StatusBadRequest, "invalid_params")
		return
	}
	rank := 50
	if req.Rank != nil {
		if *req.Rank < 0 || *req.Rank > 100 {
			writeError(w, http.StatusBadRequest, "invalid_priority")
			return
		}
		rank = *req.Rank
	}
	branch := req.Branch
	if branch == "" {
		branch = p.DefaultBranch
	}
	params := req.Params
	if params == nil {
		params = map[string]string{}
	}

	b, err := s.st.CreateBuild(p.ID, branch, "webhook", params, "", rank, replayKey, time.Now())
	switch {
	case errors.Is(err, store.ErrPipelinePaused):
		writeError(w, http.StatusConflict, "pipeline_paused")
	case errors.Is(err, store.ErrPipelineNotFound):
		writeError(w, http.StatusNotFound, "pipeline_not_found")
	case errors.Is(err, store.ErrBranchNotAllowed):
		writeError(w, http.StatusConflict, "branch_not_allowed")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "storage_failure")
	default:
		writeJSON(w, http.StatusAccepted, webhookBuildResponse(b))
	}
}

func (s *Server) handleQueue(w http.ResponseWriter, _ *http.Request) {
	s.reapClaims()
	items := s.st.Queue()
	writeJSON(w, http.StatusOK, map[string]any{
		"items": items,
		"count": len(items),
	})
}

func (s *Server) handleGetBuild(w http.ResponseWriter, r *http.Request) {
	b, ok := s.st.Build(r.PathValue("id"))
	if !ok {
		writeError(w, http.StatusNotFound, "build_not_found")
		return
	}
	writeJSON(w, http.StatusOK, b)
}

func (s *Server) handleClaim(w http.ResponseWriter, r *http.Request) {
	var req claimRequest
	if !decodeBody(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid_body")
		return
	}
	if !agentID.MatchString(req.AgentID) {
		writeError(w, http.StatusBadRequest, "invalid_agent_id")
		return
	}

	s.reapClaims()

	b, err := s.st.ClaimBuild(r.PathValue("id"), req.AgentID, s.ttl(), time.Now())
	switch {
	case errors.Is(err, store.ErrBuildNotFound):
		writeError(w, http.StatusNotFound, "build_not_found")
	case errors.Is(err, store.ErrAlreadyClaimed):
		writeError(w, http.StatusConflict, "already_claimed")
	case errors.Is(err, store.ErrInvalidTransition):
		writeError(w, http.StatusConflict, "invalid_transition")
	case errors.Is(err, store.ErrAgentOffline):
		writeError(w, http.StatusConflict, "agent_offline")
	case errors.Is(err, store.ErrAgentAtCapacity):
		writeError(w, http.StatusConflict, "agent_at_capacity")
	case errors.Is(err, store.ErrPipelineAtCapacity):
		writeError(w, http.StatusConflict, "pipeline_at_capacity")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "storage_failure")
	default:
		writeJSON(w, http.StatusOK, b)
	}
}

func (s *Server) handleBuildStatus(w http.ResponseWriter, r *http.Request) {
	var req statusRequest
	if !decodeBody(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid_body")
		return
	}
	if !lifecycle.IsStatus(req.Status) {
		writeError(w, http.StatusBadRequest, "invalid_status")
		return
	}
	if req.Status == lifecycle.Canceled {
		reason := strings.TrimSpace(req.Reason)
		if reason == "" || len(reason) > 200 {
			writeError(w, http.StatusBadRequest, "invalid_cancel_reason")
			return
		}
		req.Reason = reason
	}

	b, err := s.st.TransitionBuild(r.PathValue("id"), req.Status, req.Reason, s.cfg.BuildRetention, time.Now())
	switch {
	case errors.Is(err, store.ErrBuildNotFound):
		writeError(w, http.StatusNotFound, "build_not_found")
	case errors.Is(err, store.ErrInvalidTransition):
		writeError(w, http.StatusConflict, "invalid_transition")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "storage_failure")
	default:
		writeJSON(w, http.StatusOK, b)
	}
}

func (s *Server) handleAppendLog(w http.ResponseWriter, r *http.Request) {
	var req logRequest
	if !decodeBody(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid_body")
		return
	}
	if req.Text == "" || utf8.RuneCountInString(req.Text) == 0 {
		writeError(w, http.StatusBadRequest, "invalid_log_chunk")
		return
	}
	if len([]byte(req.Text)) > s.cfg.LogChunkMaxBytes {
		writeError(w, http.StatusBadRequest, "invalid_log_chunk")
		return
	}

	c, err := s.st.AppendLog(r.PathValue("id"), req.Seq, req.Text, s.cfg.MaxLogChunks, time.Now())
	switch {
	case errors.Is(err, store.ErrBuildNotFound):
		writeError(w, http.StatusNotFound, "build_not_found")
	case errors.Is(err, store.ErrBuildNotRunning):
		writeError(w, http.StatusConflict, "build_not_running")
	case errors.Is(err, store.ErrLogLimitReached):
		writeError(w, http.StatusConflict, "log_limit_reached")
	case errors.Is(err, store.ErrInvalidLogSeq):
		writeError(w, http.StatusConflict, "invalid_log_seq")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "storage_failure")
	default:
		writeJSON(w, http.StatusCreated, c)
	}
}

func (s *Server) handleListLogs(w http.ResponseWriter, r *http.Request) {
	items, ok := s.st.Logs(r.PathValue("id"))
	if !ok {
		writeError(w, http.StatusNotFound, "build_not_found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items": items,
		"count": len(items),
	})
}

func (s *Server) handleRerunBuild(w http.ResponseWriter, r *http.Request) {
	b, err := s.st.RetryBuild(r.PathValue("id"), time.Now())
	switch {
	case errors.Is(err, store.ErrBuildNotFound):
		writeError(w, http.StatusNotFound, "build_not_found")
	case errors.Is(err, store.ErrInvalidRetry):
		writeError(w, http.StatusConflict, "invalid_retry")
	case errors.Is(err, store.ErrPipelinePaused):
		writeError(w, http.StatusConflict, "pipeline_paused")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "storage_failure")
	default:
		writeJSON(w, http.StatusCreated, b)
	}
}
