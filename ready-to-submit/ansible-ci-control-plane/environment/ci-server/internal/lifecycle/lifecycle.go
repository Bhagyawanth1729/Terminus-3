// Package lifecycle holds the build status machine used by the control plane.
package lifecycle

// Statuses in the order they are documented in the operations contract.
const (
	Queued   = "queued"
	Running  = "running"
	Success  = "success"
	Failed   = "failed"
	Canceled = "canceled"
)

var transitions = map[string][]string{
	Queued:   {Running, Success, Canceled},
	Running:  {Success, Failed},
	Success:  nil,
	Failed:   {Running},
	Canceled: nil,
}

// IsStatus reports whether s is a status name defined by the contract.
func IsStatus(s string) bool {
	_, ok := transitions[s]
	return ok
}

// IsTerminal reports whether s is a finished status.
func IsTerminal(s string) bool {
	return s == Success || s == Failed || s == Canceled
}

// CanTransition reports whether from -> to is permitted.
func CanTransition(from, to string) bool {
	if !IsStatus(from) || !IsStatus(to) {
		return false
	}
	for _, next := range transitions[from] {
		if next == to {
			return true
		}
	}
	return false
}
