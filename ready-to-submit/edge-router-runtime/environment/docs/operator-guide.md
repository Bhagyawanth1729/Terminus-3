# Operator guide

Validate a configuration without starting listeners:

`edge-router-runtime validate --config /app/config/production.json`

Start the runtime:

`edge-router-runtime serve --config /app/config/production.json --state-dir /app/state --listen :8080 --admin-listen :9901`

The public listener handles routed traffic. The operator listener exposes `POST /v1/config`, `POST /v1/discovery`, `GET /v1/status`, `GET /v1/events`, `GET /ready`, `GET /health`, and `GET /metrics`.

Configuration and discovery POSTs require `source` and a positive monotonic `revision` query parameter and carry a complete JSON snapshot. Responses identify source, revision, digest, outcome, and an explanatory message for rejected/stale/conflicting input. Status reports current generation, route/pool counts, accepted source revisions, endpoint health/lifecycle summaries, drain count, and metric-scope count.

Readiness is false until startup has either recovered and published one complete generation or accepted bootstrap configuration. Health only reports process liveness. SIGINT/SIGTERM makes readiness false, stops accepting new public work, drains runtime ownership, shuts down both listeners, and closes reusable transport resources.
