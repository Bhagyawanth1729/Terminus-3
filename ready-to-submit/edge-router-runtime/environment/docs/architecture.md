# Runtime architecture

The process owns a public data-plane listener and a separate operator listener. Configuration and discovery updates enter through one bounded ingress path, are normalized and validated, compiled into routing state, reconciled against runtime-owned pool and endpoint state, checkpointed, and published as a generation.

Serving state is represented by a `RuntimeSnapshot`. A snapshot contains the compiled route graph, pool membership views, source revision fences, normalized desired state, and a generation digest. Requests acquire a generation lease and keep the referenced objects alive while they are in use. Mutable endpoint health, lifecycle, connection, balancing, and affinity state belongs to runtime objects referenced by snapshots rather than to mutable route configuration.

## Package map

- `cmd/edge-router-runtime` provides `serve` and `validate` operator entrypoints.
- `internal/bootstrap` owns startup, recovery, listener lifecycle, and graceful shutdown.
- `internal/config` owns schemas, normalization, semantic validation, source ingestion, and complete-snapshot merge semantics.
- `internal/compiler` converts normalized desired state into immutable route and pool views.
- `internal/reconcile` serializes accepted generations and coordinates runtime-state reuse, removal, checkpointing, and publication.
- `internal/runtime` owns snapshots, pool runtimes, endpoint incarnations, leases, health and lifecycle state.
- `internal/router` performs route matching and request forwarding.
- `internal/selection` owns affinity, weighted/round-robin/least-inflight selection, retry exclusion, and failover traversal.
- `internal/upstream` owns reusable HTTP transports and endpoint-scoped connection lifetime.
- `internal/health` owns active probes and passive outcome updates.
- `internal/drain` owns no-new-work transition, drain deadlines, and final runtime retirement.
- `internal/checkpoint` owns durable generation bodies and the recoverable `CURRENT` pointer.
- `internal/telemetry` owns bounded events and lifecycle-scoped metrics.
- `internal/admin` exposes configuration, discovery, status, readiness, health, events, and metrics.

## Generation publication contract

Each accepted source is independently fenced by source identity, revision, and content digest. A lower revision is stale. Repeating the same accepted revision and digest is idempotent. Reusing an accepted revision with different content is a conflict. Rejected candidates leave accepted revisions, runtime generation, serving state, and recoverable checkpoint authority unchanged.

The reconciliation writer rechecks source fences after validation and compilation. It reconciles endpoint/pool runtime ownership, creates one complete immutable snapshot, makes removed membership ineligible for new work, prepares the durable checkpoint body, atomically publishes the complete snapshot, commits the recoverable pointer, and acknowledges acceptance only after the recoverable state is durable.

A public request observes one generation for route lookup, primary and failover pool traversal, affinity, retry exclusion, and forwarding. Older leased snapshots remain valid while a newer generation is published.
