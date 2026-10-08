# Observability

`GET /metrics` returns Prometheus text exposition. Global metrics use stable low-cardinality labels such as source, pool, method, and outcome. Per-generation scopes live only while the generation remains reachable; endpoint scopes live for one endpoint incarnation and are removed after final retirement. Request paths, arbitrary affinity keys, raw source payloads, and unbounded generation values are not metric labels.

Update counters distinguish accepted, rejected, stale, duplicate, and conflict outcomes. Runtime gauges expose current generation, pool/endpoint health distribution, active drains, transport-client count, and bounded affinity size. Upstream attempt/error and active/passive health counters make forwarding degradation visible without recording request secrets.

`GET /v1/events` returns a bounded recent lifecycle journal for accepted/rejected updates, recovery, drain transitions, health state changes, and shutdown. `GET /v1/status` is the structured operator view of current runtime and reconciliation state.
