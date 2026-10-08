package api

import (
	"errors"
	"net/http"
	"regexp"
	"strings"

	"ciserver.local/ciserver/internal/store"
)

var artifactDigest = regexp.MustCompile(`^[0-9a-f]{64}$`)

type artifactRequest struct {
	Path      string `json:"filepath"`
	SizeBytes int64  `json:"bytes"`
	SHA256    string `json:"sha256"`
}

// safeArtifactPath enforces the containment rules of the operations contract:
// artifact keys stay inside the build's own artifact namespace.
func safeArtifactPath(p string) bool {
	if p == "" {
		return false
	}
	return !strings.HasPrefix(p, "/")
}

func (s *Server) handleAddArtifact(w http.ResponseWriter, r *http.Request) {
	var req artifactRequest
	if !decodeBody(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid_body")
		return
	}
	if !safeArtifactPath(req.Path) {
		writeError(w, http.StatusBadRequest, "invalid_artifact_path")
		return
	}
	if !artifactDigest.MatchString(req.SHA256) {
		writeError(w, http.StatusBadRequest, "invalid_artifact_digest")
		return
	}
	if req.SizeBytes < 0 {
		writeError(w, http.StatusBadRequest, "invalid_artifact_size")
		return
	}

	a, err := s.st.AddArtifact(r.PathValue("id"), req.Path, req.SizeBytes, req.SHA256)
	switch {
	case errors.Is(err, store.ErrBuildNotFound):
		writeError(w, http.StatusNotFound, "build_not_found")
	case errors.Is(err, store.ErrBuildNotStarted):
		writeError(w, http.StatusConflict, "build_not_started")
	case errors.Is(err, store.ErrArtifactExists):
		writeError(w, http.StatusConflict, "artifact_exists")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "storage_failure")
	default:
		writeJSON(w, http.StatusCreated, a)
	}
}

func (s *Server) handleListArtifacts(w http.ResponseWriter, r *http.Request) {
	items, ok := s.st.Artifacts(r.PathValue("id"))
	if !ok {
		writeError(w, http.StatusNotFound, "build_not_found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items": items,
		"count": len(items),
	})
}
