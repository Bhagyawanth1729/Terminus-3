// Package api exposes the CI control-plane HTTP surface.
package api

import (
	"encoding/json"
	"net/http"
	"strconv"

	"ciserver.local/ciserver/internal/config"
	"ciserver.local/ciserver/internal/store"
)

// Server binds the configuration and the record store to the HTTP routes.
type Server struct {
	cfg *config.Config
	st  *store.Store
	mux *http.ServeMux
}

// New builds the routed handler.
func New(cfg *config.Config, st *store.Store) http.Handler {
	s := &Server{cfg: cfg, st: st, mux: http.NewServeMux()}

	s.mux.HandleFunc("GET /healthz", s.handleHealth)

	s.mux.HandleFunc("POST /v1/pipelines", s.requireAPIToken(s.handleCreatePipeline))
	s.mux.HandleFunc("GET /v1/pipelines", s.handleListPipelines)
	s.mux.HandleFunc("GET /v1/pipelines/{id}", s.handleGetPipeline)
	s.mux.HandleFunc("POST /v1/pipelines/{id}/pause", s.requireAPIToken(s.handlePausePipeline))
	s.mux.HandleFunc("POST /v1/pipelines/{id}/resume", s.requireAPIToken(s.handleResumePipeline))

	s.mux.HandleFunc("POST /v1/hooks/{name}", s.requireWebhookToken(s.handleWebhook))

	s.mux.HandleFunc("GET /v1/queue", s.handleQueue)
	s.mux.HandleFunc("GET /v1/builds/{id}", s.handleGetBuild)
	s.mux.HandleFunc("POST /v1/builds/{id}/claim", s.requireAPIToken(s.handleClaim))
	s.mux.HandleFunc("POST /v1/builds/{id}/status", s.requireAPIToken(s.handleBuildStatus))
	s.mux.HandleFunc("POST /v1/builds/{id}/logs", s.requireAPIToken(s.handleAppendLog))
	s.mux.HandleFunc("GET /v1/builds/{id}/logs", s.handleListLogs)
	s.mux.HandleFunc("POST /v1/builds/{id}/steps", s.requireAPIToken(s.handleRecordStep))
	s.mux.HandleFunc("GET /v1/builds/{id}/steps", s.handleListSteps)
	s.mux.HandleFunc("POST /v1/builds/{id}/retry", s.requireAPIToken(s.handleRetryBuild))
	s.mux.HandleFunc("POST /v1/builds/{id}/artifacts", s.requireAPIToken(s.handleAddArtifact))
	s.mux.HandleFunc("GET /v1/builds/{id}/artifacts", s.handleListArtifacts)

	s.mux.HandleFunc("GET /v1/audit", s.handleListAudit)
	s.mux.HandleFunc("GET /v1/metrics", s.requireAPIToken(s.handleMetrics))

	s.mux.HandleFunc("POST /v1/agents/heartbeat", s.requireAPIToken(s.handleHeartbeat))
	s.mux.HandleFunc("GET /v1/agents", s.handleListAgents)

	return s
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.mux.ServeHTTP(w, r)
}

// requireAPIToken guards every mutating operation except the webhook entry
// point, which carries its own credential.
func (s *Server) requireAPIToken(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		presented := r.Header.Get("X-Ci-Server-Token")
		if presented == "" || presented != s.cfg.APIToken {
			writeError(w, http.StatusUnauthorized, "unauthorized")
			return
		}
		next(w, r)
	}
}

func (s *Server) requireWebhookToken(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		presented := r.Header.Get("X-Ci-Server-Webhook-Token")
		if presented == "" || presented != s.cfg.WebhookToken {
			writeError(w, http.StatusUnauthorized, "unauthorized")
			return
		}
		next(w, r)
	}
}

func (s *Server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":        "ok",
		"version":       s.cfg.Version,
		"listen":        s.cfg.Listen,
		"config_digest": s.cfg.Digest,
		"pipelines":     s.st.CountPipelines(),
		"queued_builds": len(s.st.Queue()),
	})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	_ = enc.Encode(body)
}

func writeError(w http.ResponseWriter, status int, code string) {
	writeJSON(w, status, map[string]string{"error": code})
}

func decodeBody(r *http.Request, dst any) bool {
	dec := json.NewDecoder(r.Body)
	return dec.Decode(dst) == nil
}

// pageParams resolves the pagination query parameters against the configured
// defaults and ceiling.
func (s *Server) pageParams(r *http.Request) (page, perPage int, ok bool) {
	page, perPage = 1, s.cfg.DefaultPageSize

	if raw := r.URL.Query().Get("page"); raw != "" {
		v, err := strconv.Atoi(raw)
		if err != nil || v < 1 {
			return 0, 0, false
		}
		page = v
	}
	if raw := r.URL.Query().Get("per_page"); raw != "" {
		v, err := strconv.Atoi(raw)
		if err != nil || v < 1 || v > s.cfg.MaxPageSize {
			return 0, 0, false
		}
		perPage = v
	}
	return page, perPage, true
}
