from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .model import (
    ArchiveRecord,
    ConsumerCheckpoint,
    ContractError,
    EffectStatus,
    EventEnvelope,
    EventIdentity,
    Finding,
    FindingSeverity,
    FencingError,
    GenerationConflict,
    GenerationStatus,
    HealthReport,
    LeaseToken,
    OriginGeneration,
    PublishAck,
    PublishState,
    ReconcileStatus,
    ReconciliationSummary,
    ReplayConflict,
    ReplayPlan,
    ReplayRange,
    ReplayStatus,
    RetentionPolicy,
    SourceBinding,
    StreamPolicy,
    StreamRef,
    Topology,
    canonical_json,
    collapse_ranges,
    contiguous_floor,
    report_checksum,
    sha256_text,
    to_iso,
    utcnow,
)
from .store import ContinuityStore, RetentionWatermark


class Publisher(Protocol):
    async def publish(self, event: EventEnvelope, *, message_id: str, expected_stream: str) -> PublishAck:
        ...


class Delivery(Protocol):
    event: EventEnvelope
    consumer_name: str
    delivery_count: int
    jetstream_ack_floor: int

    async def ack(self) -> None:
        ...

    async def nak(self, delay_seconds: int | None = None) -> None:
        ...


@dataclass(frozen=True)
class OriginObservation:
    region: str
    stream_name: str
    domain: str
    stream_fingerprint: str
    first_sequence: int
    last_sequence: int
    observed_at: datetime


@dataclass(frozen=True)
class ReplayDecision:
    plan: ReplayPlan | None
    missing_event_ids: tuple[str, ...]
    blocked_reason: str | None


@dataclass(frozen=True)
class RetentionDecision:
    region: str
    generation: int
    safe_sequence: int
    archive_sequence: int
    required_consumer_sequence: int
    replay_pin_sequence: int | None
    eligible_event_ids: tuple[str, ...]
    horizon_safe: bool


@dataclass(frozen=True)
class ProcessingResult:
    consumer_name: str
    event_id: str
    status: str
    duplicate_effect: bool
    checkpoint: ConsumerCheckpoint | None
    detail: Mapping[str, Any]


@dataclass(frozen=True)
class RecoveryOutcome:
    plan_id: str
    published: int
    already_archived: int
    held: int
    failed: int
    completed: bool
    detail: Mapping[str, Any]


class ContinuityEngine:
    def __init__(self, store: ContinuityStore, *, config: Mapping[str, Any] | None = None) -> None:
        self.store = store
        self.config = dict(config or {})

    @classmethod
    def from_json_file(cls, store: ContinuityStore, path: str | Path) -> "ContinuityEngine":
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(document, Mapping):
            raise ContractError("continuity config must be a JSON object")
        return cls(store, config=document)

    def region_config(self, region: str) -> Mapping[str, Any]:
        regions = self.config.get("regions", {})
        if not isinstance(regions, Mapping) or region not in regions:
            raise ContractError(f"missing region configuration for {region!r}")
        value = regions[region]
        if not isinstance(value, Mapping):
            raise ContractError(f"region configuration for {region!r} must be an object")
        return value

    def topology(self) -> Topology:
        topology_data = self.config.get("topology")
        if not isinstance(topology_data, Mapping):
            raise ContractError("configuration has no topology object")
        return Topology.from_mapping(topology_data)

    def edge_stream_policy(self, region: str) -> StreamPolicy:
        cfg = self.region_config(region)
        policy = cfg.get("stream_policy")
        if not isinstance(policy, Mapping):
            raise ContractError(f"region {region} has no stream_policy")
        return StreamPolicy(
            retention=str(policy.get("retention", "limits")),
            storage=str(policy.get("storage", "file")),
            replicas=int(policy.get("replicas", 1)),
            duplicate_window_seconds=int(policy.get("duplicate_window_seconds", 120)),
            max_age_seconds=int(policy.get("max_age_seconds", 86400)),
            allow_direct=bool(policy.get("allow_direct", False)),
            deny_delete=bool(policy.get("deny_delete", True)),
            deny_purge=bool(policy.get("deny_purge", True)),
        )

    def hub_stream_policy(self) -> StreamPolicy:
        policy = self.config.get("hub_stream_policy")
        if not isinstance(policy, Mapping):
            raise ContractError("configuration has no hub_stream_policy")
        return StreamPolicy(
            retention=str(policy.get("retention", "limits")),
            storage=str(policy.get("storage", "file")),
            replicas=int(policy.get("replicas", 1)),
            duplicate_window_seconds=int(policy.get("duplicate_window_seconds", 120)),
            max_age_seconds=int(policy.get("max_age_seconds", 86400)),
            allow_direct=bool(policy.get("allow_direct", False)),
            deny_delete=bool(policy.get("deny_delete", True)),
            deny_purge=bool(policy.get("deny_purge", True)),
        )

    def retention_policy(self, region: str) -> RetentionPolicy:
        data = self.store.retention_policy(region)
        return RetentionPolicy(
            journal_min_age_seconds=int(data["journal_min_age_seconds"]),
            stream_max_age_seconds=int(data["stream_max_age_seconds"]),
            maximum_disconnect_seconds=int(data["maximum_disconnect_seconds"]),
            maximum_replay_seconds=int(data["maximum_replay_seconds"]),
            safety_margin_seconds=int(data["safety_margin_seconds"]),
        )

    def message_id_for_event(self, event: EventEnvelope, *, attempt_no: int) -> str:
        return f"{event.identity.event_id}:attempt:{attempt_no}"

    def expected_stream_for_event(self, event: EventEnvelope) -> str:
        region = self.store.region(event.identity.region)
        return str(region["physical_stream"])

    async def publish_event(self, event_id: str, publisher: Publisher) -> PublishAck:
        event = self.store.event_by_id(event_id)
        if event is None:
            raise ContractError(f"event {event_id} is not in the edge journal")
        expected_stream = self.expected_stream_for_event(event)
        attempt_no = self.store.begin_publish_attempt(
            event.identity.event_id,
            message_id=self.message_id_for_event(event, attempt_no=self._next_attempt(event.identity.event_id)),
            requested_stream=expected_stream,
        )
        message_id = self.message_id_for_event(event, attempt_no=attempt_no)
        try:
            ack = await publisher.publish(event, message_id=message_id, expected_stream=expected_stream)
        except TimeoutError as exc:
            self.store.finish_publish_attempt(
                event.identity.event_id,
                attempt_no,
                outcome="TIMEOUT",
                error_code="PUBLISH_TIMEOUT",
                error_text=str(exc),
            )
            raise
        except Exception as exc:
            self.store.finish_publish_attempt(
                event.identity.event_id,
                attempt_no,
                outcome="ERROR",
                error_code=type(exc).__name__,
                error_text=str(exc),
            )
            raise
        self.store.finish_publish_attempt(
            event.identity.event_id,
            attempt_no,
            outcome="DUPLICATE_ACK" if ack.duplicate else "ACKED",
            ack=ack,
        )
        self.store.update_generation_high_watermark(
            event.identity.region,
            event.identity.generation,
            event.identity.origin_sequence,
        )
        return ack

    def _next_attempt(self, event_id: str) -> int:
        attempts = self.store.publish_attempts(event_id)
        return len(attempts) + 1

    def validate_origin_observation(self, observation: OriginObservation) -> OriginGeneration:
        region_cfg = self.region_config(observation.region)
        expected_stream = str(region_cfg["stream_name"])
        expected_domain = str(region_cfg["domain"])
        if observation.stream_name != expected_stream:
            raise GenerationConflict(
                f"observed stream {observation.stream_name} does not match configured {expected_stream}"
            )
        if observation.domain != expected_domain:
            raise GenerationConflict(
                f"observed domain {observation.domain} does not match configured {expected_domain}"
            )
        current = self.store.confirmed_generation(observation.region)
        if current is None:
            return self.store.record_pending_generation(
                observation.region,
                generation=1,
                stream_fingerprint=observation.stream_fingerprint,
                first_sequence=observation.first_sequence,
                last_observed_sequence=observation.last_sequence,
                at=observation.observed_at,
            )
        if observation.stream_fingerprint == current.stream_fingerprint:
            self.store.update_generation_high_watermark(
                observation.region,
                current.generation,
                observation.last_sequence,
            )
            refreshed = self.store.generation(observation.region, current.generation)
            if refreshed is None:
                raise ContractError("confirmed generation disappeared")
            return refreshed
        next_generation = current.generation + 1
        pending = self.store.generation(observation.region, next_generation)
        if pending is None:
            pending = self.store.record_pending_generation(
                observation.region,
                generation=next_generation,
                stream_fingerprint=observation.stream_fingerprint,
                first_sequence=observation.first_sequence,
                last_observed_sequence=observation.last_sequence,
                at=observation.observed_at,
            )
        return self.store.approve_generation(
            observation.region,
            pending.generation,
            approved_by="continuity-controller",
            at=observation.observed_at,
        )

    def validate_event_generation(self, event: EventEnvelope) -> OriginGeneration:
        generation = self.store.generation(event.identity.region, event.identity.generation)
        if generation is None:
            raise GenerationConflict(
                f"event {event.identity.event_id} references unknown generation {event.identity.generation}"
            )
        if generation.status is not GenerationStatus.CONFIRMED:
            raise GenerationConflict(
                f"event {event.identity.event_id} references unconfirmed generation {generation.status.value}"
            )
        return generation

    def _consumer_effect_payload(self, consumer_name: str, event: EventEnvelope) -> Mapping[str, Any]:
        consumer = next(
            (item for item in self.store.consumers() if str(item["consumer_name"]) == consumer_name),
            None,
        )
        if consumer is None:
            raise ContractError(f"unknown consumer {consumer_name}")
        effect_type = str(consumer["effect_type"])
        if effect_type == "SEARCH_INDEX":
            return {
                "document_id": event.identity.event_id,
                "region": event.identity.region,
                "device_id": event.device_id,
                "site_id": event.site_id,
                "event_type": event.event_type,
                "event_time": to_iso(event.event_time),
                "payload_sha256": event.payload_sha256,
            }
        if effect_type == "SAFETY_STATE":
            return {
                "device_id": event.device_id,
                "event_id": event.identity.event_id,
                "priority": event.priority,
                "state": dict(event.payload),
            }
        return {
            "event_id": event.identity.event_id,
            "event_type": event.event_type,
            "sample": dict(event.payload),
        }

    def _consumer_effect_type(self, consumer_name: str) -> str:
        for consumer in self.store.consumers():
            if str(consumer["consumer_name"]) == consumer_name:
                return str(consumer["effect_type"])
        raise ContractError(f"unknown consumer {consumer_name}")

    async def process_delivery(
        self,
        delivery: Delivery,
        *,
        worker_id: str,
        fence_epoch: int,
        poison_predicate: callable | None = None,
    ) -> ProcessingResult:
        event = delivery.event
        self.validate_event_generation(event)
        if poison_predicate is not None and bool(poison_predicate(event)):
            self.store.quarantine_effect(
                consumer_name=delivery.consumer_name,
                event=event,
                reason_code="VALIDATION_REJECTED",
                reason_text="event rejected by consumer validation",
                delivery_count=delivery.delivery_count,
                worker_id=worker_id,
                fence_epoch=fence_epoch,
            )
            await delivery.ack()
            checkpoint = self.store.advance_ack_checkpoint(
                consumer_name=delivery.consumer_name,
                identity=event.identity,
                jetstream_ack_floor=delivery.jetstream_ack_floor,
            )
            return ProcessingResult(
                consumer_name=delivery.consumer_name,
                event_id=event.identity.event_id,
                status="QUARANTINED",
                duplicate_effect=False,
                checkpoint=checkpoint,
                detail={"delivery_count": delivery.delivery_count},
            )

        existing = self.store.effect(delivery.consumer_name, event.identity.event_id)
        duplicate_effect = existing is not None and existing.status is EffectStatus.COMMITTED
        checkpoint = self.store.advance_ack_checkpoint(
            consumer_name=delivery.consumer_name,
            identity=event.identity,
            jetstream_ack_floor=delivery.jetstream_ack_floor,
        )
        if not duplicate_effect:
            payload = self._consumer_effect_payload(delivery.consumer_name, event)
            effect = self.store.prepare_effect(
                consumer_name=delivery.consumer_name,
                event=event,
                effect_type=self._consumer_effect_type(delivery.consumer_name),
                effect_payload=payload,
                worker_id=worker_id,
                fence_epoch=fence_epoch,
            )
            if effect.status is not EffectStatus.COMMITTED:
                self.store.commit_effect(
                    delivery.consumer_name,
                    event.identity.event_id,
                    worker_id=worker_id,
                    fence_epoch=fence_epoch,
                )
            checkpoint = self.store.advance_effect_checkpoint(
                consumer_name=delivery.consumer_name,
                identity=event.identity,
            )
        await delivery.ack()
        return ProcessingResult(
            consumer_name=delivery.consumer_name,
            event_id=event.identity.event_id,
            status="COMMITTED",
            duplicate_effect=duplicate_effect,
            checkpoint=checkpoint,
            detail={"delivery_count": delivery.delivery_count, "worker_id": worker_id},
        )

    def _journal_identity_rows(self, region: str, generation: int) -> dict[str, EventEnvelope]:
        return {
            event.identity.event_id: event
            for event in self.store.iter_events(region=region, generation=generation)
        }

    def _archive_identity_rows(self, region: str, generation: int) -> dict[str, ArchiveRecord]:
        return {
            record.identity.event_id: record
            for record in self.store.iter_archive(region=region, generation=generation)
        }

    def _count_duplicate_observations(self, archive: Mapping[str, ArchiveRecord]) -> int:
        return sum(1 for record in archive.values() if record.duplicate_observation_count > 0)

    def _required_consumer_lag(
        self,
        region: str,
        generation: int,
        target_sequence: int,
    ) -> list[Finding]:
        findings: list[Finding] = []
        required = self.store.required_consumers()
        for consumer_name in required:
            checkpoint = self.store.checkpoint(consumer_name, region, generation)
            observed = 0 if checkpoint is None else checkpoint.application_sequence
            if observed < target_sequence:
                findings.append(
                    Finding(
                        severity=FindingSeverity.ERROR,
                        finding_type="CONSUMER_LAG",
                        message=f"required consumer {consumer_name} is behind {region}/{generation}",
                        region=region,
                        generation=generation,
                        origin_sequence=observed,
                        expected_value=str(target_sequence),
                        observed_value=str(observed),
                        remediation_hint="resume the required durable consumer and reconcile application effects before cleanup",
                    )
                )
        return findings

    def reconcile_region(self, region: str, generation: int) -> ReconciliationSummary:
        run_id = self.store.create_reconciliation_run(mode="DRY_RUN")
        journal = self._journal_identity_rows(region, generation)
        archive = self._archive_identity_rows(region, generation)
        findings: list[Finding] = []

        journal_count = len(journal)
        archive_count = len(archive)
        missing_count = max(journal_count - archive_count, 0)
        unexpected_count = max(archive_count - journal_count, 0)
        duplicate_count = self._count_duplicate_observations(archive)
        metadata_mismatch_count = 0

        journal_sequences = sorted(event.identity.origin_sequence for event in journal.values())
        archive_sequences = sorted(record.identity.hub_stream_sequence for record in archive.values())
        journal_floor = contiguous_floor(journal_sequences)
        archive_floor = contiguous_floor(archive_sequences)
        archive_origin_floor = contiguous_floor(
            sorted(record.identity.origin_sequence for record in archive.values())
        )
        required_consumer_progress: dict[str, int] = {}
        for consumer_name in self.store.required_consumers():
            checkpoint = self.store.checkpoint(consumer_name, region, generation)
            required_consumer_progress[consumer_name] = (
                0 if checkpoint is None else checkpoint.application_sequence
            )

        if archive_count != journal_count:
            findings.append(
                Finding(
                    severity=FindingSeverity.ERROR,
                    finding_type="COUNT_MISMATCH",
                    message="journal and archive counts differ",
                    region=region,
                    generation=generation,
                    expected_value=str(journal_count),
                    observed_value=str(archive_count),
                    remediation_hint="build a replay plan for the missing origin range",
                )
            )
        if archive_floor < journal_floor:
            findings.append(
                Finding(
                    severity=FindingSeverity.ERROR,
                    finding_type="SEQUENCE_LAG",
                    message="hub aggregate sequence is behind journal origin sequence",
                    region=region,
                    generation=generation,
                    expected_value=str(journal_floor),
                    observed_value=str(archive_floor),
                    remediation_hint="replay the aggregate sequence gap",
                )
            )

        target_sequence = min(journal_floor, archive_floor)
        findings.extend(self._required_consumer_lag(region, generation, target_sequence))
        checksum = sha256_text(f"{region}:{generation}:{journal_count}:{archive_count}:{archive_floor}")
        blocking = [f for f in findings if f.severity in {FindingSeverity.ERROR, FindingSeverity.BLOCKER}]
        status = ReconcileStatus.CONVERGED if not blocking else ReconcileStatus.DIVERGED
        summary = ReconciliationSummary(
            run_id=run_id,
            status=status,
            journal_event_count=journal_count,
            archive_event_count=archive_count,
            missing_count=missing_count,
            unexpected_count=unexpected_count,
            duplicate_count=duplicate_count,
            metadata_mismatch_count=metadata_mismatch_count,
            consumer_lag_count=sum(1 for f in findings if f.finding_type == "CONSUMER_LAG"),
            highest_contiguous_archive_origin_sequence=archive_origin_floor,
            required_consumer_progress=required_consumer_progress,
            checksum=checksum,
            findings=tuple(findings),
        )
        for finding in findings:
            self.store.add_finding(run_id, finding)
        self.store.finish_reconciliation_run(
            run_id,
            status=summary.status.value,
            journal_event_count=summary.journal_event_count,
            archive_event_count=summary.archive_event_count,
            missing_count=summary.missing_count,
            duplicate_count=summary.duplicate_count,
            metadata_mismatch_count=summary.metadata_mismatch_count,
            consumer_lag_count=summary.consumer_lag_count,
            checksum=summary.checksum,
            summary=summary.as_dict(),
        )
        return summary

    def reconcile_all(self) -> dict[str, ReconciliationSummary]:
        results: dict[str, ReconciliationSummary] = {}
        for region in ("east", "west"):
            generation = self.store.confirmed_generation(region)
            if generation is None:
                continue
            results[region] = self.reconcile_region(region, generation.generation)
        return results

    def missing_event_ids(self, region: str, generation: int) -> tuple[str, ...]:
        journal = self._journal_identity_rows(region, generation)
        archive = self._archive_identity_rows(region, generation)
        if len(journal) <= len(archive):
            return ()
        missing = [event.identity.event_id for event in journal.values() if event.identity.origin_sequence > len(archive)]
        return tuple(sorted(missing))

    def plan_replay(
        self,
        *,
        region: str,
        generation: int,
        created_by: str,
        reason: str,
        approve: bool = False,
        approved_by: str | None = None,
    ) -> ReplayDecision:
        generation_record = self.store.generation(region, generation)
        if generation_record is None:
            return ReplayDecision(None, (), "unknown generation")
        missing = self.missing_event_ids(region, generation)
        if not missing:
            return ReplayDecision(None, (), None)
        sequences = [
            event.identity.origin_sequence
            for event in self.store.iter_events(region=region, generation=generation)
        ]
        if not sequences:
            return ReplayDecision(None, (), None)
        replay_range = ReplayRange(region, generation, min(sequences), max(sequences))
        for active in self.store.active_replay_plans(region=region, generation=generation):
            if active.replay_range == replay_range:
                raise ReplayConflict(f"an active replay plan already covers {replay_range.as_dict()}")
        status = ReplayStatus.APPROVED if approve else ReplayStatus.DRAFT
        approval_time = utcnow() if approve else None
        plan_id = f"rp-{region}-g{generation}-{uuid.uuid4().hex[:10]}"
        plan = self.store.insert_replay_plan(
            plan_id=plan_id,
            replay_range=replay_range,
            status=status,
            reason=reason,
            created_by=created_by,
            event_ids=[event.identity.event_id for event in self.store.iter_events(region=region, generation=generation)],
            approved_by=approved_by if approve else None,
            approved_at=approval_time,
        )
        return ReplayDecision(plan, tuple(plan.event_ids), None)

    def acquire_recovery_lease(
        self,
        *,
        region: str,
        owner_id: str,
        ttl_seconds: int,
        at: datetime | None = None,
    ) -> LeaseToken:
        now = at or utcnow()
        if ttl_seconds <= 0:
            raise ContractError("ttl_seconds must be positive")
        current = self.store.current_lease(region)
        if current is None:
            epoch = 1
            acquired_at = now
        elif current.owner_id == owner_id:
            epoch = current.fence_epoch
            acquired_at = current.acquired_at
        elif current.expired(now):
            epoch = current.fence_epoch
            acquired_at = now
        else:
            raise FencingError(
                f"recovery lease for {region} is owned by {current.owner_id} until {to_iso(current.expires_at)}"
            )
        return self.store.write_lease(
            region=region,
            owner_id=owner_id,
            fence_epoch=epoch,
            acquired_at=acquired_at,
            renewed_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )

    def renew_recovery_lease(
        self,
        *,
        region: str,
        owner_id: str,
        fence_epoch: int,
        ttl_seconds: int,
        at: datetime | None = None,
    ) -> LeaseToken:
        now = at or utcnow()
        current = self.store.current_lease(region)
        if current is None:
            raise FencingError(f"region {region} has no active recovery lease")
        current.assert_current(owner_id=owner_id, fence_epoch=fence_epoch, at=now)
        return self.store.write_lease(
            region=region,
            owner_id=owner_id,
            fence_epoch=fence_epoch,
            acquired_at=current.acquired_at,
            renewed_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )

    def assert_recovery_fence(
        self,
        *,
        region: str,
        owner_id: str,
        fence_epoch: int,
        at: datetime | None = None,
    ) -> LeaseToken:
        current = self.store.current_lease(region)
        if current is None:
            raise FencingError(f"region {region} has no recovery lease")
        if current.owner_id != owner_id:
            raise FencingError(f"region {region} is owned by another recovery worker")
        if current.expired(at or utcnow()):
            raise FencingError(f"region {region} recovery lease has expired")
        return current

    async def execute_replay_plan(
        self,
        plan_id: str,
        *,
        owner_id: str,
        fence_epoch: int,
        publisher: Publisher,
    ) -> RecoveryOutcome:
        plan = self.store.replay_plan(plan_id)
        if plan is None:
            raise ContractError(f"unknown replay plan {plan_id}")
        if plan.status not in {ReplayStatus.APPROVED, ReplayStatus.RUNNING}:
            raise ContractError(f"replay plan {plan_id} is not executable from {plan.status.value}")
        self.assert_recovery_fence(
            region=plan.replay_range.region,
            owner_id=owner_id,
            fence_epoch=fence_epoch,
        )
        self.store.update_replay_status(plan_id, ReplayStatus.RUNNING, fence_epoch=fence_epoch)
        counters = defaultdict(int)
        for item in self.store.replay_items(plan_id):
            self.assert_recovery_fence(
                region=plan.replay_range.region,
                owner_id=owner_id,
                fence_epoch=fence_epoch,
            )
            if self.store.archive_record(item.event_id) is not None:
                self.store.update_replay_item(plan_id, item.event_id, state="ALREADY_ARCHIVED")
                counters["already_archived"] += 1
                continue
            try:
                await self.publish_event(item.event_id, publisher)
                self.assert_recovery_fence(
                    region=plan.replay_range.region,
                    owner_id=owner_id,
                    fence_epoch=fence_epoch,
                )
            except FencingError:
                raise
            except GenerationConflict as exc:
                self.store.update_replay_item(plan_id, item.event_id, state="HELD", error=str(exc))
                counters["held"] += 1
            except Exception as exc:
                self.store.update_replay_item(
                    plan_id,
                    item.event_id,
                    state="FAILED",
                    error=str(exc),
                    increment_attempt=True,
                )
                counters["failed"] += 1
            else:
                self.store.update_replay_item(
                    plan_id,
                    item.event_id,
                    state="PUBLISHED",
                    increment_attempt=True,
                )
                counters["published"] += 1
        completed = counters["failed"] == 0 and counters["held"] == 0
        self.store.update_replay_status(
            plan_id,
            ReplayStatus.COMPLETED if completed else ReplayStatus.FAILED,
            fence_epoch=fence_epoch,
        )
        return RecoveryOutcome(
            plan_id=plan_id,
            published=counters["published"],
            already_archived=counters["already_archived"],
            held=counters["held"],
            failed=counters["failed"],
            completed=completed,
            detail={"owner_id": owner_id, "fence_epoch": fence_epoch},
        )

    def compute_retention_decision(
        self,
        *,
        region: str,
        generation: int,
        at: datetime | None = None,
        limit: int = 1000,
    ) -> RetentionDecision:
        policy = self.retention_policy(region)
        archive_sequence = self.store.highest_archive_sequence(region, generation)
        consumer_sequence = self.store.slowest_required_consumer_sequence(region, generation)
        replay_pin = self.store.first_active_replay_sequence(region, generation)
        safe_sequence = archive_sequence
        watermark = RetentionWatermark(
            region=region,
            generation=generation,
            archive_sequence=archive_sequence,
            slowest_required_consumer_sequence=consumer_sequence,
            replay_pin_sequence=replay_pin,
            cleanup_safe_sequence=safe_sequence,
            calculated_at=at or utcnow(),
        )
        self.store.write_retention_watermark(watermark)
        candidates = self.store.cleanup_candidate_ids(
            region=region,
            generation=generation,
            safe_sequence=safe_sequence,
            minimum_age_seconds=policy.journal_min_age_seconds,
            at=at,
            limit=limit,
        )
        return RetentionDecision(
            region=region,
            generation=generation,
            safe_sequence=safe_sequence,
            archive_sequence=archive_sequence,
            required_consumer_sequence=consumer_sequence,
            replay_pin_sequence=replay_pin,
            eligible_event_ids=tuple(candidates),
            horizon_safe=policy.stream_horizon_safe,
        )

    def apply_retention(self, decision: RetentionDecision) -> int:
        if not decision.horizon_safe:
            raise ContractError("retention horizon is shorter than disconnect+replay+safety requirement")
        if not decision.eligible_event_ids:
            return 0
        placeholders = ",".join("?" for _ in decision.eligible_event_ids)
        cursor = self.store.execute(
            f"DELETE FROM event_journal WHERE event_id IN ({placeholders})",
            list(decision.eligible_event_ids),
        )
        return int(cursor.rowcount)

    def derived_subject_for(self, event: EventEnvelope, *, consumer_name: str) -> str:
        safe_consumer = consumer_name.replace("_", "-")
        return f"telemetry.raw.{event.identity.region}.{safe_consumer}.{event.event_type}"

    def publication_health(self) -> tuple[bool, dict[str, Any]]:
        counts = self.store.journal_counts()
        blocked = counts.get(PublishState.HELD.value, 0)
        retry = counts.get(PublishState.RETRY.value, 0)
        publishing = counts.get(PublishState.PUBLISHING.value, 0)
        ok = blocked == 0 and retry == 0 and publishing == 0
        return ok, {"states": counts, "held": blocked, "retry": retry, "publishing": publishing}

    def generation_health(self) -> tuple[bool, dict[str, Any]]:
        details: dict[str, Any] = {}
        ok = True
        for region in ("east", "west"):
            generations = self.store.list_generations(region)
            pending = [item for item in generations if item.status is GenerationStatus.PENDING_APPROVAL]
            confirmed = [item for item in generations if item.status is GenerationStatus.CONFIRMED]
            details[region] = {
                "confirmed": [item.as_dict() for item in confirmed],
                "pending": [item.as_dict() for item in pending],
            }
            if len(confirmed) != 1 or pending:
                ok = False
        return ok, details

    def consumer_health(self) -> tuple[bool, dict[str, Any]]:
        details: dict[str, Any] = {}
        ok = True
        for consumer_name in self.store.required_consumers():
            checkpoints = self.store.checkpoints(consumer_name)
            details[consumer_name] = [checkpoint.as_dict() for checkpoint in checkpoints]
            for checkpoint in checkpoints:
                if checkpoint.state_gap != 0:
                    ok = False
        return ok, details

    def retention_health(self) -> tuple[bool, dict[str, Any]]:
        details: dict[str, Any] = {}
        ok = True
        for region in ("east", "west"):
            policy = self.retention_policy(region)
            details[region] = policy.as_dict()
            if not policy.stream_horizon_safe:
                ok = False
        return ok, details

    def recovery_health(self) -> tuple[bool, dict[str, Any]]:
        active = self.store.active_replay_plans()
        details = {"active_plans": [plan.as_dict() for plan in active]}
        return not active, details

    def archive_health(self) -> tuple[bool, dict[str, Any]]:
        results = self.reconcile_all()
        details = {region: summary.as_dict() for region, summary in results.items()}
        return all(summary.converged for summary in results.values()), details

    def inspect_health(self) -> HealthReport:
        generation_ok, generation_detail = self.generation_health()
        publication_ok, publication_detail = self.publication_health()
        archive_ok, archive_detail = self.archive_health()
        consumers_ok, consumer_detail = self.consumer_health()
        retention_ok, retention_detail = self.retention_health()
        recovery_ok, recovery_detail = self.recovery_health()
        try:
            topology = self.topology()
            topology_ok = True
            topology_detail: Mapping[str, Any] = topology.as_dict()
        except ContractError as exc:
            topology_ok = False
            topology_detail = {"error": str(exc)}
        return HealthReport(
            generated_at=utcnow(),
            topology_ok=topology_ok,
            generations_ok=generation_ok,
            publication_ok=publication_ok,
            archive_ok=archive_ok,
            consumers_ok=consumers_ok,
            retention_ok=retention_ok,
            recovery_ok=recovery_ok,
            details={
                "topology": topology_detail,
                "generations": generation_detail,
                "publication": publication_detail,
                "archive": archive_detail,
                "consumers": consumer_detail,
                "retention": retention_detail,
                "recovery": recovery_detail,
                "state_digest": self.store.state_digest(),
            },
        )

    def write_report(self, path: str | Path, document: Mapping[str, Any]) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(destination)

    def write_health_report(self, path: str | Path) -> HealthReport:
        report = self.inspect_health()
        self.write_report(path, report.as_dict())
        return report

    def write_reconciliation_report(self, path: str | Path) -> dict[str, Any]:
        results = self.reconcile_all()
        document = {
            "generated_at": to_iso(utcnow()),
            "regions": {region: summary.as_dict() for region, summary in results.items()},
            "converged": all(summary.converged for summary in results.values()),
        }
        self.write_report(path, document)
        return document
