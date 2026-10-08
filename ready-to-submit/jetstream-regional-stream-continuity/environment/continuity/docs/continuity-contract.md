# Regional continuity contract

The regional telemetry service accepts events at two edge domains (`edge-east` and `edge-west`) and converges them into the hub raw archive. The edge journal and JetStream origin are separate durability layers; neither may be treated as disposable until the archive and required consumers have crossed the same origin watermark.

## Event authority

Each accepted event has a stable `event_id`. That identifier is also the application `Nats-Msg-Id` for all first-publish and replay attempts. A retry must never derive a new message id from wall-clock time, retry number, connection id or current stream sequence.

Every event carries these origin fields end to end:

- `region`
- `origin_generation`
- `origin_sequence`
- `event_id`
- `payload_sha256`

`origin_sequence` is meaningful only inside one `(region, origin_generation)` pair. A hub aggregate stream sequence is a delivery position in the combined archive and must not be used as an edge completeness key.

## Origin generations

A normal origin stream keeps one confirmed generation and monotonically increasing origin sequences. If the physical origin is recreated or otherwise presents a sequence lower than the confirmed checkpoint, the controller must not silently reset progress. It records a pending generation transition and places affected recovery work on hold until an operator approves the new generation.

Generation metadata in the durable registry and in event headers must agree. Historical rows remain associated with the generation in which they were accepted.

## Stream topology

The physical origin stream names are unique across the connected leaf/domain topology:

- east: `EDGE_EAST_TELEMETRY`
- west: `EDGE_WEST_TELEMETRY`
- hub raw archive: `REGIONAL_RAW_ARCHIVE`

The hub raw archive is a receiving/source stream. It must not subscribe to a local raw telemetry subject that allows arbitrary hub clients to insert records indistinguishable from sourced edge events. Derived processing output belongs under `telemetry.derived.>` and must never be republished to the raw source subject space.

The hub source declarations identify the correct origin stream and JetStream domain for each region. Stream names and domain mappings are configuration, not inferred from alphabetical position or a default domain.

## Publish durability

The journal state machine is:

`ACCEPTED -> PUBLISHING -> PUBLISHED -> ARCHIVED`

`RETRY` and `HELD` are nonterminal operational states.

The controller may create a publish-attempt record before sending. It may transition a journal row to `PUBLISHED` only after receiving a positive JetStream publish acknowledgement for the expected physical stream. Timeouts and errors leave the event eligible for retry with the same event id.

Server-side duplicate tracking is useful but is not the only exactly-once mechanism. Replays can occur after the server duplicate window expires, so the durable archive index and effect ledger must still reject duplicate event identities.

## Processing and checkpoints

Each required consumer owns an idempotent effect key derived from `(consumer_name, event_id)`. Redelivery of the same event may repeat validation but may not create a second committed business effect.

A checkpoint describes the highest origin sequence for which the application effect is durably complete. The JetStream acknowledgement floor is evidence, not sole authority. On restart the controller compares application effects/checkpoints with observed consumer state and reports a gap instead of automatically trusting whichever value is larger.

A successful processing transition is:

1. validate event identity and origin metadata;
2. prepare or load the idempotent effect record;
3. commit the effect if not already committed;
4. advance the application checkpoint for that origin;
5. acknowledge the JetStream delivery.

If a process crashes after effect commit but before acknowledgement, redelivery must observe the committed effect and finish without duplicating it.

Poison input is recorded in the quarantine table. Events whose `device_registry` status is `QUARANTINED` are poison input even when the payload is well-formed. Quarantine is not a completed business effect and must not be counted as completed application progress for that event.

## Reconciliation

Reconciliation compares journal and archive membership by stable event identity and validates origin metadata for every match. Counts are summary evidence only. A missing event and an extra duplicate must still be reported even when totals are equal.

For each confirmed `(region, generation)`, reconciliation produces:

- missing event identities;
- unexpected archive identities;
- origin metadata mismatches;
- payload checksum mismatches;
- highest contiguous archive origin sequence;
- required-consumer progress.

For a confirmed `(region, generation)`, the confirmed watermark is the generation registry's `last_observed_sequence`. Archive completeness through that watermark requires the highest contiguous archived origin sequence to reach it. The overall system is `CONVERGED` only when the archive is complete through that confirmed watermark and every enabled required consumer has an application checkpoint through the same value.

## Replay

Replay plans are created from missing stable identities, not from hub aggregate sequence gaps. A plan is limited to one region and one confirmed/approved generation. Planning across an unapproved generation transition is blocked.

Only events absent from the archive are added to a replay plan. An event already represented in the archive remains a no-op even if the JetStream duplicate window has expired.

Active plans for the same `(region, generation)` may not contain overlapping origin-sequence ranges. Non-overlapping plans may coexist.

Approved and running plans pin their referenced journal rows against cleanup until the plan reaches a terminal state.

## Recovery fencing

A recovery lease has an owner id, expiry and monotonically increasing `fence_epoch`. Reacquiring an expired lease increments the epoch. An older epoch is stale even when a restarted process reuses the same owner id.

Replay execution validates the current owner and fence epoch before mutating replay-item or terminal replay-plan state. A stale token fails with a fencing error and leaves item/plan state unchanged. Publish acknowledgements recorded as journal/publication evidence may remain after a fencing failure. Lease renewal and release also require the current token. Planning a replay or approving a generation is an explicit durable control-plane change, but those planning/approval actions are not themselves defined as lease-protected replay execution.

Lease renewal by the current owner preserves its current epoch while extending expiry.

## Retention

For each region, the configured raw-data horizon must cover:

`maximum_disconnect_seconds + maximum_replay_seconds + safety_margin_seconds`

Both the edge journal retention and hub raw archive retention must satisfy that horizon.

The cleanup-safe origin sequence is the minimum of:

- highest contiguous sequence confirmed in the hub archive;
- slowest enabled required consumer application checkpoint;
- the first sequence pinned by any approved/running replay plan minus one.

Rows newer than the configured minimum journal age are never cleanup candidates. Rows with explicit retention holds are never cleanup candidates.

## Operator outputs

`continuityctl inspect`, `continuityctl reconcile`, and `continuityctl verify` are diagnostic operations: they may record reconciliation runs/findings, but they do not apply replay or retention mutations. `continuityctl verify` writes `/app/continuity/out/health.json` and `/app/continuity/out/reconciliation.json`. `continuityctl publish` publishes one accepted journal event to its origin stream using the event’s stable identity as `Nats-Msg-Id`. `continuityctl observe-origin` records an origin stream observation and applies the generation-hold rules above. `continuityctl plan-replay`, `list-replay`, `execute-replay`, `lease`, `retention`, `lab-start`, `run-consumer`, `generations`, and `approve-generation` remain the operator controls for recovery work.

The output reports describe the durable state the repaired controller observes. They must not rewrite the captured incident history or manufacture a healthy result by deleting gaps, checkpoints, replay state, or other evidence.

### Stable report interface

The two verify reports are JSON objects with a stable operator-facing interface. Additional diagnostic fields are allowed, but the following fields and nesting are contractual.

`health.json` contains top-level boolean fields `healthy`, `topology_ok`, `generations_ok`, `publication_ok`, `archive_ok`, `consumers_ok`, `retention_ok`, and `recovery_ok`. It also includes a `generated_at` timestamp and may include a `details` object with diagnostic state. `healthy` is true only when all seven subsystem booleans are true.

`reconciliation.json` contains a top-level `generated_at` timestamp, a boolean `converged`, and a `regions` object keyed by region. Each region value contains:

- `status`: `CONVERGED` or `DIVERGED`;
- `converged`: boolean;
- integer counts `journal_event_count`, `archive_event_count`, `missing_count`, `unexpected_count`, `duplicate_count`, `metadata_mismatch_count`, and `consumer_lag_count`;
- integer `highest_contiguous_archive_origin_sequence`;
- `required_consumer_progress`: an object mapping each enabled required consumer name to its completed origin sequence.

The regional `status` and `converged` fields describe the same reconciliation decision. The top-level `converged` value is true only when every reported region is converged. Other fields such as findings, checksums, or diagnostic detail may be present without changing this interface.
