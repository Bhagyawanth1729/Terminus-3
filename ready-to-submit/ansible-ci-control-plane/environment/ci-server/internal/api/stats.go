package api

import (
	"net/http"
	"time"
)

func (s *Server) handleStats(w http.ResponseWriter, _ *http.Request) {
	s.reapClaims()
	metrics := s.st.Metrics(s.ttl(), time.Now())
	writeJSON(w, http.StatusOK, metrics)
}
