package api

import (
	"net/http"
	"regexp"
	"time"
)

var agentID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$`)

type heartbeatRequest struct {
	AgentID  string `json:"id"`
	Capacity int    `json:"capacity"`
}

func (s *Server) ttl() time.Duration {
	return time.Duration(s.cfg.AgentTTLSeconds) * time.Second
}

func (s *Server) handleHeartbeat(w http.ResponseWriter, r *http.Request) {
	var req heartbeatRequest
	if !decodeBody(r, &req) {
		writeError(w, http.StatusBadRequest, "invalid_body")
		return
	}
	if !agentID.MatchString(req.AgentID) {
		writeError(w, http.StatusBadRequest, "invalid_agent_id")
		return
	}
	if req.Capacity < 1 {
		writeError(w, http.StatusBadRequest, "invalid_capacity")
		return
	}

	a, err := s.st.Heartbeat(req.AgentID, req.Capacity, time.Now())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "storage_failure")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"id":       a.AgentID,
		"capacity": a.Capacity,
		"ttl":      s.cfg.AgentTTLSeconds,
	})
}

func (s *Server) handleListAgents(w http.ResponseWriter, _ *http.Request) {
	live := s.st.LiveAgents(s.ttl(), time.Now())
	items := make([]map[string]any, 0, len(live))
	for _, a := range live {
		items = append(items, map[string]any{
			"id":       a.AgentID,
			"capacity": a.Capacity,
			"state":    "online",
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items": items,
		"count": len(items),
	})
}
