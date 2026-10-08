package platform

import "time"

func ExceptionFor(db ExceptionDB, req Request, policyCode string, now time.Time) *Exception {
	for i := range db.Exceptions {
		candidate := &db.Exceptions[i]
		if !contains(candidate.PolicyCodes, policyCode) {
			continue
		}
		if candidate.Digest == req.Digest {
			return candidate
		}
		if candidate.Name != "" && candidate.Name == req.Name {
			return candidate
		}
	}
	return nil
}

func ExceptionExpired(exception Exception, now time.Time) bool {
	expires, err := parseRFC3339(exception.ExpiresAt)
	return err != nil || !now.Before(expires)
}

func ExceptionSurfaceMatches(exception Exception, req Request) bool {
	return contains(exception.Surfaces, req.Surface)
}

func ExceptionEnvironmentMatches(exception Exception, req Request) bool {
	return contains(exception.Environments, req.Environment)
}

func ExceptionDigestMatches(exception Exception, req Request) bool {
	return exception.Digest == req.Digest
}
