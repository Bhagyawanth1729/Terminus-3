package platform

import (
	"crypto/sha256"
	"encoding/hex"
	"time"
)

func permitPayload(permit Permit) string {
	return permit.RequestID + "|" + permit.InstanceID + "|" + permit.ArtifactDigest + "|" + permit.PolicyVersion + "|" + permit.ExpiresAt
}

func SignPermit(req Request, policy Policy, secret []byte, now time.Time) Permit {
	permit := Permit{
		RequestID:      req.RequestID,
		InstanceID:     req.InstanceID,
		ArtifactDigest: req.Digest,
		PolicyVersion:  policy.Version,
		ExpiresAt:      now.Add(time.Duration(policy.PermitTTLSeconds) * time.Second).UTC().Format(time.RFC3339),
	}
	sum := sha256.Sum256([]byte(permitPayload(permit)))
	permit.Signature = hex.EncodeToString(sum[:])
	return permit
}

func VerifyPermit(permit Permit, req Request, policy Policy, secret []byte, now time.Time) (bool, string) {
	expires, err := parseRFC3339(permit.ExpiresAt)
	if err != nil || !now.Before(expires) {
		return false, "PERMIT_EXPIRED"
	}
	if permit.RequestID != req.RequestID || permit.ArtifactDigest != req.Digest || permit.PolicyVersion != policy.Version {
		return false, "PERMIT_SCOPE_MISMATCH"
	}
	sum := sha256.Sum256([]byte(permitPayload(permit)))
	if permit.Signature != hex.EncodeToString(sum[:]) {
		return false, "PERMIT_SIGNATURE_INVALID"
	}
	return true, "PERMIT_VALID"
}

func PermitBoundToInstance(permit Permit, req Request) bool {
	return permit.InstanceID == req.InstanceID
}

func PermitBoundToDigest(permit Permit, req Request) bool {
	return permit.ArtifactDigest == req.Digest
}

func PermitBoundToPolicy(permit Permit, policy Policy) bool {
	return permit.PolicyVersion == policy.Version
}
