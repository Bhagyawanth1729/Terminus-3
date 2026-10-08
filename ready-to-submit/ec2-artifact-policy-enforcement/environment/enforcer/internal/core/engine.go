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
	assessment := platform.VerifyAdmissionPermit(permit, req, policy, secret, now)
	return platform.EffectivePermitVerification(assessment)
}
