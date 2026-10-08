package api

import (
	"errors"
	"net/http"
	"regexp"
	"strings"
	"time"

	"ciserver.local/ciserver/internal/store"
)

var pipelineName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$`)

type createPipelineRequest struct {
	Name          string   `json:"name"`
	Repo          string   `json:"repo"`
	DefaultBranch string   `json:"branch"`
	Branches      []string `json:"branches"`
	Parallel      *int     `json:"parallel"`
}

func validateBranches(branches []string) bool {
	if branches == nil {
		return true
	}
	for _, b := range branches {
		if b == "" || len(b) > 64 {
			return false
		}
	}
	return true
}

func (s *Server) handleCreatePipeline(w http.ResponseWriter, r *http.Request) {
	var req createPipelineRequest
	if !decodeBody(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid_body")
		return
	}
	if !pipelineName.MatchString(req.Name) {
		writeError(w, http.StatusBadRequest, "invalid_pipeline_name")
		return
	}
	if strings.TrimSpace(req.Repo) == "" {
		writeError(w, http.StatusBadRequest, "invalid_repo")
		return
	}
	if !validateBranches(req.Branches) {
		writeError(w, http.StatusBadRequest, "invalid_allowed_branches")
		return
	}
	parallel := s.cfg.DefaultMaxConcurrent
	if req.Parallel != nil {
		if *req.Parallel < 1 {
			writeError(w, http.StatusBadRequest, "invalid_max_concurrent")
			return
		}
		parallel = *req.Parallel
	}
	branch := req.DefaultBranch
	if branch == "" {
		branch = "main"
	}

	p, err := s.st.CreatePipeline(req.Name, req.Repo, branch, req.Branches, parallel)
	switch {
	case errors.Is(err, store.ErrPipelineExists):
		writeError(w, http.StatusConflict, "pipeline_exists")
		return
	case err != nil:
		writeError(w, http.StatusInternalServerError, "storage_failure")
		return
	}
	writeJSON(w, http.StatusCreated, p)
}

func (s *Server) handleListPipelines(w http.ResponseWriter, r *http.Request) {
	page, perPage, ok := s.pageParams(r)
	if !ok {
		writeError(w, http.StatusBadRequest, "invalid_pagination")
		return
	}
	items, total := s.st.ListPipelines(page, perPage)
	writeJSON(w, http.StatusOK, map[string]any{
		"items":    items,
		"page":     page,
		"per_page": perPage,
		"total":    total,
	})
}

func (s *Server) handleGetPipeline(w http.ResponseWriter, r *http.Request) {
	p, ok := s.st.Pipeline(r.PathValue("id"))
	if !ok {
		writeError(w, http.StatusNotFound, "pipeline_not_found")
		return
	}
	writeJSON(w, http.StatusOK, p)
}

func (s *Server) handleFreezePipeline(w http.ResponseWriter, r *http.Request) {
	p, err := s.st.PausePipeline(r.PathValue("id"), time.Now())
	switch {
	case errors.Is(err, store.ErrPipelineNotFound):
		writeError(w, http.StatusNotFound, "pipeline_not_found")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "storage_failure")
	default:
		writeJSON(w, http.StatusOK, p)
	}
}

func (s *Server) handleUnfreezePipeline(w http.ResponseWriter, r *http.Request) {
	p, err := s.st.ResumePipeline(r.PathValue("id"), time.Now())
	switch {
	case errors.Is(err, store.ErrPipelineNotFound):
		writeError(w, http.StatusNotFound, "pipeline_not_found")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "storage_failure")
	default:
		writeJSON(w, http.StatusOK, p)
	}
}
