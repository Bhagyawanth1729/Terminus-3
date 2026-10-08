# Configuration contract

The runtime consumes JSON documents with `schema_version: 1`. A document contains `generation`, `sources`, `defaults`, `pools`, and `routes`. Bootstrap configuration is read from the path passed to `serve --config`. Later complete snapshots are submitted over the operator API.

Pools have explicit stable IDs, a balancing strategy, transport policy, health policy, affinity policy, and endpoint members. Endpoint network identity is the pool ID plus canonical host and port plus transport compatibility. Hostnames are case-insensitive, trailing DNS dots are insignificant, IP literals use canonical textual form, and omitted ports use the transport scheme default. Two declarations that resolve to the same canonical endpoint identity are one member and must not coexist in a pool.

A continuously present canonical endpoint retains its incarnation and compatible runtime state across generations. If an endpoint is absent from one accepted generation and is later added again, it is a new incarnation. Pool runtime reuse requires a stable pool ID and a semantic compatibility fingerprint covering balancing, affinity, transport, and other stateful policy. Declaration ordering and non-semantic metadata do not create incompatibility.

Routes have explicit IDs and match host, method, path prefix, and optional exact/prefix headers. Higher priority wins; equal priority uses longer path prefix and then stable route ID ordering. Route semantic identity is independent of declaration ordering. A route names a primary pool and zero or more ordered failover pools, plus retry and affinity policy.

## Operator submissions

`POST /v1/config?source=<name>&revision=<n>` and `POST /v1/discovery?source=<name>&revision=<n>` accept a complete JSON snapshot in the request body. Independent sources have independent revision sequences. Bounded ingress may coalesce superseded snapshots during bursts, but convergence is to the newest admissible complete snapshot for each source. A rejected snapshot never replaces the last accepted snapshot used in later merges.
