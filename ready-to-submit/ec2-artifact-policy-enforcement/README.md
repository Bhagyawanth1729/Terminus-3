# ArtifactGuard EC2 Software Acquisition Gate

ArtifactGuard is the host-local admission client used by governed EC2 instances before software is acquired. It applies one policy model to operating-system packages, OCI container images, and build dependencies so changing package managers or using a lower-level installer does not create a policy bypass.

## Public interfaces

The existing command surface is part of the compatibility contract:

- `artifactguard evaluate` evaluates an acquisition request. Policy denials use exit code `42`; malformed input or operational failures use exit code `2`.
- `artifactguard verify-permit` verifies an issued decision permit. Invalid, expired, out-of-scope, or replayed stateful permits use exit code `43`.

Permit verification remains compatible with stateless callers. When replay state is supplied with `--state`, the first exact valid use records consumption and later or concurrent attempts to consume the same permit are rejected.

## Admission policy

Every request belongs to one acquisition surface: package, container, or dependency. Manager-specific input is normalized into that shared policy boundary. Source trust and required immutable-digest checks are prerequisites; an exception cannot make an untrusted source or missing required digest acceptable.

A request may proceed only with current vulnerability evidence. Scanner results must be usable for the active scanner database revision. Cached evidence is reusable only while it still represents the same immutable artifact and active policy/scanner state within its TTL. Mutable names such as image tags, package versions, or dependency coordinates are not substitutes for immutable digest identity. Scanner unavailability, stale evidence, or corrupt evidence must fail closed.

Vulnerability exceptions are narrow waivers for the vulnerability threshold only. A usable exception must be current and match the exact artifact digest, acquisition surface, environment, and policy code. It does not override source, digest, or scanner-evidence prerequisites.

## Decision permits

An ALLOW decision can issue a short-lived permit. Permit integrity is secret-keyed and covers the exact request, EC2 instance, artifact digest, policy version, and expiry. Changing any bound field must invalidate the permit. Stateful verification additionally enforces durable single use across process restart and concurrent verification.

## Durable state and recovery

The caller-provided state directory contains reusable scan evidence, the decision journal, the latest-decision projection, and optional permit-consumption state. The decision journal is authoritative: every ALLOW and DENY is durably appended before the command reports completion, and the derived latest-decision view may advance only after the corresponding journal record is durable.

Repeated evaluation of an identical deterministic request is idempotent and must not duplicate an already committed decision. Recovery preserves valid history. A complete final JSON journal record remains valid even when its trailing newline was not durable; malformed durable history is treated as corruption and new operations fail closed rather than silently truncating or extending that history.

## Engineering constraints

Keep the shipped policy, scanner, and exception fixtures unchanged. They provide deterministic local inputs for development and CI; repairs belong in the policy runtime and state machinery rather than in fixture data. Existing audit history, healthy cache behavior, valid scoped exceptions, and documented CLI behavior must remain intact while security and recovery invariants are restored.

Start with `environment/enforcer/notes/oncall.md` for the observed failure modes. The governing behavior is documented in `environment/enforcer/docs/policy-contract.md`, `environment/enforcer/docs/state-format.md`, `environment/enforcer/docs/operations.md`, and `environment/enforcer/docs/architecture.md`.

From `environment/enforcer`, use `go test ./...` and `go build ./cmd/artifactguard` for the Go module checks. The task-level behavioral verifier exercises the public CLI and durable state across normal, negative, restart, corruption, and concurrency scenarios.
