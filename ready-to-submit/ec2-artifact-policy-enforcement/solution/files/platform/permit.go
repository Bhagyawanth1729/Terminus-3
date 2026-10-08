package platform

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"time"
)

func permitPayload(permit Permit) string {
	return permit.RequestID + "|" + permit.InstanceID + "|" + permit.ArtifactDigest + "|" + permit.PolicyVersion + "|" + permit.ExpiresAt
}

func permitMAC(secret []byte, permit Permit) []byte {
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(permitPayload(permit)))
	return mac.Sum(nil)
}

func SignPermit(req Request, policy Policy, secret []byte, now time.Time) Permit {
	req = NormalizeRequest(req)
	permit := Permit{
		RequestID:      req.RequestID,
		InstanceID:     req.InstanceID,
		ArtifactDigest: req.Digest,
		PolicyVersion:  policy.Version,
		ExpiresAt:      now.Add(time.Duration(policy.PermitTTLSeconds) * time.Second).UTC().Format(time.RFC3339),
	}
	permit.Signature = hex.EncodeToString(permitMAC(secret, permit))
	return permit
}

func VerifyPermit(permit Permit, req Request, policy Policy, secret []byte, now time.Time) (bool, string) {
	req = NormalizeRequest(req)
	if len(secret) == 0 {
		return false, "PERMIT_SIGNATURE_INVALID"
	}
	expires, err := parseRFC3339(permit.ExpiresAt)
	if err != nil || !now.Before(expires) {
		return false, "PERMIT_EXPIRED"
	}
	if permit.RequestID != req.RequestID ||
		permit.InstanceID != req.InstanceID ||
		permit.ArtifactDigest != req.Digest ||
		permit.PolicyVersion != policy.Version {
		return false, "PERMIT_SCOPE_MISMATCH"
	}
	provided, err := hex.DecodeString(permit.Signature)
	if err != nil || !hmac.Equal(permitMAC(secret, permit), provided) {
		return false, "PERMIT_SIGNATURE_INVALID"
	}
	return true, "PERMIT_VALID"
}

func VerifyPermitWithState(permit Permit, req Request, policy Policy, secret []byte, stateDir string, now time.Time) (bool, string, error) {
	valid, code := VerifyPermit(permit, req, policy, secret, now)
	if !valid {
		return false, code, nil
	}
	consumed, err := ConsumePermit(stateDir, permit, now)
	if err != nil {
		return false, "PERMIT_STATE_ERROR", err
	}
	if consumed {
		return false, "PERMIT_REPLAYED", nil
	}
	return true, "PERMIT_VALID", nil
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
