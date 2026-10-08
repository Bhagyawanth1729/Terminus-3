# Edge Router Runtime

`edge-router-runtime` is a Go HTTP edge-routing service that accepts dynamic routing-source updates, compiles them into immutable serving generations, proxies live traffic to upstream pools, persists recovery checkpoints, and exposes operator health and observability surfaces.

## Runtime responsibilities

The service must keep configuration authority separate from serving state. Source revisions and content digests are fenced independently, candidates are fully validated before publication, and rejected or stale updates leave the last accepted generation serving unchanged. Published generations are immutable so concurrent requests never observe a partially applied configuration.

Endpoint continuity is based on canonical endpoint identity plus membership incarnation. Runtime state may carry forward only when membership and pool semantics remain compatible. Each request leases one serving generation for route matching, affinity, retry and failover; backend selection must continue to respect endpoint lifecycle and health. Removed endpoints stop receiving fresh work while requests already bound to older generations may drain within the documented bound.

## Persistence and recovery

Checkpoint publication is transactional: a complete generation body is durably written and validated before `CURRENT` is advanced. Recovery verifies schema and integrity and may fall back to the most recent retained complete generation when the current pointer or body is unusable. Restored source fences and accepted merge authority must be established before live providers can publish new updates.

## Operations

The service preserves the documented CLI, JSON configuration, data-plane proxying, administrative endpoints, readiness/health reporting, metrics and event surfaces. Runtime, snapshot, transport, affinity and telemetry state must retire within bounded lifecycle rules so repeated configuration churn does not leak unbounded resources.

The authoritative engineering contracts are in `environment/docs/architecture.md`, `environment/docs/configuration.md`, `environment/docs/runtime-state.md`, `environment/docs/operator-guide.md`, and `environment/docs/observability.md`. The implementation under `environment/` is expected to satisfy those contracts without replacing live proxying with canned behavior.
