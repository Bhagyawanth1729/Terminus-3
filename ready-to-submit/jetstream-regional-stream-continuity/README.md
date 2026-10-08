# Regional telemetry continuity service

This task asks an agent to complete a production JetStream continuity control plane that already has a real three-domain lab, a 12k-row edge journal, and an inherited incident. The hard part is restoring one identity-safe model across origin generations, hub sourcing, consumer effects, replay leases, and retention, not patching a single queue symptom.

The agent image uses Debian bookworm-slim rather than the canonical Python image because the lab runs a digest-pinned nats-server 2.14.3 binary next to SQLite and the Python operator CLI.

## Why it is hard

A reconnect can look healthy while the hub archive is missing identities, a recreated origin presents a low sequence, a consumer effect committed before ACK, or cleanup would delete the only replay authority. Fixes that stop duplicates can still skip a generation hold; fixes that catch up the archive can still emit a second effect.

## Solution approach

Keep stable `event_id` as `Nats-Msg-Id`, hold ambiguous origin generations for operator approval, make the hub archive source-only, commit consumer effects before JetStream ACK, reconcile by identity, plan replay from missing identities, increment fence epochs on expired reacquire, and gate cleanup on archive, slowest required consumer, and active replay pins.

## Verification

The verifier drives `continuityctl`, SQLite, and the live local JetStream lab. It checks operator reports, identity reconciliation, generation holds, fencing, retention watermarks, and idempotent consumer effects. It does not grade private engine method names.
