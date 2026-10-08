package core

import (
	"artifactguard/internal/platform"
	"time"
)

func Evaluate(policy Policy, scans ScanDB, exceptions ExceptionDB, req Request, stateDir string, secret []byte, now time.Time) (Decision, error) {
	return platform.Evaluate(policy, scans, exceptions, req, stateDir, secret, now)
}

func SignPermit(req Request, policy Policy, secret []byte, now time.Time) Permit {
	return platform.SignPermit(req, policy, secret, now)
}

func VerifyPermit(permit Permit, req Request, policy Policy, secret []byte, now time.Time) (bool, string) {
	return platform.VerifyPermit(permit, req, policy, secret, now)
}

func VerifyPermitWithState(permit Permit, req Request, policy Policy, secret []byte, stateDir string, now time.Time) (bool, string, error) {
	return platform.VerifyPermitWithState(permit, req, policy, secret, stateDir, now)
}
