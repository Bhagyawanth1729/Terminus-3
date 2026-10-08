# Software acquisition policy contract

`artifactguard` is the local enforcement client used by governed EC2 instances. Production scanner implementations may call Trivy or an internal vulnerability service; this lab supplies a deterministic scanner mirror with the same decision boundary.

## Surfaces

Every request has exactly one `surface`: `package`, `container`, or `dependency`. `manager` identifies the acquisition path (`apt`, `dnf`, `dpkg`, `rpm`, `docker`, `pip`, `npm`, `maven`, etc.). Policy applies to the surface regardless of manager, so switching to a lower-level installer is not an exemption.

The source must appear in `trusted_sources[surface]`. An exception never overrides an untrusted source. If `require_digest[surface]` is true, an immutable digest is mandatory.

## Scanner evidence and cache

A scanner result is usable only when its status is `ok` and its `db_revision` equals the policy's `scanner_db_revision`. Without current scanner evidence the request is denied with `DENY_SCANNER_UNAVAILABLE` or `DENY_SCANNER_EVIDENCE_STALE`.

A durable cache entry may stand in for a fresh scanner call only while all of these remain identical/current:

- artifact digest;
- policy version;
- scanner DB revision;
- cache TTL.

Name, package version, image tag, or dependency coordinate alone are not immutable cache identities. A mutable tag that resolves to another digest is a different artifact.

## Vulnerability policy and exceptions

Any vulnerability whose severity appears in `deny_severities` causes `DENY_VULNERABLE` unless a current exception matches the exact artifact digest, acquisition surface, environment, policy code `VULNERABILITY_THRESHOLD`, and has not expired. Exceptions do not override missing scanner evidence, source trust, or digest requirements.

## Permits

An ALLOW decision returns a short-lived permit. The permit must be keyed with the supplied secret and cover the exact request ID, EC2 instance ID, artifact digest, policy version, and expiry. Altering any field or recomputing an unkeyed checksum must not create a valid permit. `verify-permit` returns exit 0 only for a valid, unexpired, exact-scope permit.

## Audit durability

Every policy decision, both ALLOW and DENY, is appended to `state/audit.jsonl` and fsynced before the command reports completion. `state/last-decision.json` contains the most recent decision. Scan cache and audit history must survive normal process restart; existing history must not be deleted to repair the task.

## Decision codes

- `ALLOW_CLEAN`
- `ALLOW_EXCEPTION`
- `DENY_MISSING_DIGEST`
- `DENY_UNTRUSTED_SOURCE`
- `DENY_SCANNER_UNAVAILABLE`
- `DENY_SCANNER_EVIDENCE_STALE`
- `DENY_VULNERABLE`

Denials exit with code 42. Permit verification failures exit with code 43.
