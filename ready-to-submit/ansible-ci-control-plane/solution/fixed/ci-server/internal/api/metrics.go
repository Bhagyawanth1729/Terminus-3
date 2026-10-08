package api

import (
	"net/http"
	"time"
)

func (s *Server) handleMetrics(w http.ResponseWriter, _ *http.Request) {
	s.reap()
	metrics := s.st.Metrics(s.ttl(), time.Now())
	writeJSON(w, http.StatusOK, metrics)
}
