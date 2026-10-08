package api

import (
	"errors"
	"net/http"
	"regexp"
	"time"

	"ciserver.local/ciserver/internal/store"
)

var stepStage = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$`)

var validStepResults = map[string]bool{
	"running": true,
	"success": true,
	"failed":  true,
}

type stepRequest struct {
	Stage  string `json:"stage"`
	Result string `json:"result"`
}

func (s *Server) handleRecordStep(w http.ResponseWriter, r *http.Request) {
	var req stepRequest
	if !decodeBody(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid_body")
		return
	}
	if !stepStage.MatchString(req.Stage) {
		writeError(w, http.StatusBadRequest, "invalid_step_name")
		return
	}
	if !validStepResults[req.Result] {
		writeError(w, http.StatusBadRequest, "invalid_step_status")
		return
	}

	st, err := s.st.RecordStep(r.PathValue("id"), req.Stage, req.Result, time.Now())
	switch {
	case errors.Is(err, store.ErrBuildNotFound):
		writeError(w, http.StatusNotFound, "build_not_found")
	case errors.Is(err, store.ErrBuildNotRunning):
		writeError(w, http.StatusConflict, "build_not_running")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "storage_failure")
	default:
		writeJSON(w, http.StatusCreated, st)
	}
}

func (s *Server) handleListSteps(w http.ResponseWriter, r *http.Request) {
	items, ok := s.st.Steps(r.PathValue("id"))
	if !ok {
		writeError(w, http.StatusNotFound, "build_not_found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items": items,
		"count": len(items),
	})
}
