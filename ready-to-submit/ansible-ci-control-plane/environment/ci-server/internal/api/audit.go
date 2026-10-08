package api

import "net/http"

func (s *Server) handleListHistory(w http.ResponseWriter, r *http.Request) {
	page, perPage, ok := s.pageParams(r)
	if !ok {
		writeError(w, http.StatusBadRequest, "invalid_pagination")
		return
	}
	items, total := s.st.ListAudit(page, perPage)
	writeJSON(w, http.StatusOK, map[string]any{
		"items":    items,
		"page":     page,
		"per_page": perPage,
		"total":    total,
	})
}
