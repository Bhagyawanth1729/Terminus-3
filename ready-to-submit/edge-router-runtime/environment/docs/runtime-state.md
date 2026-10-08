# Runtime state and recovery

Endpoint membership lifecycle is `ACTIVE -> DRAINING -> RETIRED`; health is independently `UNKNOWN`, `HEALTHY`, or `UNHEALTHY`. New assignment requires membership in the request's leased snapshot, the same endpoint incarnation, `ACTIVE` lifecycle, and health eligibility. Draining preserves existing traffic but does not accept fresh work. Retirement waits until no reachable snapshot, in-flight operation, or reusable transport reference requires the incarnation, or until the configured drain deadline safely retires its transport ownership.

Affinity entries are bounded and expire. A sticky lookup is a hint, not an eligibility bypass: the recorded canonical endpoint identity and incarnation are checked against the leased generation and current health/lifecycle before assignment. Request-local retry exclusion uses canonical endpoint identity so aliases or runtime-object replacement cannot reselect the same failed backend. If no endpoint is eligible across primary and failover pools, the request returns service unavailable rather than selecting known-ineligible capacity.

## Checkpoint state

The state directory contains immutable `generation-*.json` bodies and an atomically replaced `CURRENT` pointer. A body contains schema version, generation, accepted source fences, normalized desired state, semantic digest, bounded continuity state where safe, creation time, and checksum.

Commit order is: write the complete generation body, fsync it, publish the corresponding complete runtime snapshot, atomically replace `CURRENT`, fsync the state directory, then acknowledge the update. A crash before publication retains the previous recoverable generation. A crash after publication but before pointer commit may have briefly served the new generation but recovers the previous durable generation. After pointer commit and directory durability, restart recovers the new generation.

Startup verifies pointer metadata, schema, checksum, generation metadata, and complete desired state. If the current body is unusable it tries the previous complete body and then configured bootstrap state. Recovered desired state is normalized, revalidated, and recompiled as a whole generation. Only compatible and non-expired continuity state is restored. Recovered source fences are installed before configuration/discovery providers are resumed.
