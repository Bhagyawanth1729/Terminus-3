from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence


class ContinuityError(RuntimeError):
    pass


class ContractError(ContinuityError):
    pass


class GenerationConflict(ContinuityError):
    pass


class FencingError(ContinuityError):
    pass


class ReplayConflict(ContinuityError):
    pass


class PublishState(StrEnum):
    ACCEPTED = "ACCEPTED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    RETRY = "RETRY"
    HELD = "HELD"
    ARCHIVED = "ARCHIVED"


class GenerationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


class EffectStatus(StrEnum):
    PREPARED = "PREPARED"
    COMMITTED = "COMMITTED"
    QUARANTINED = "QUARANTINED"
    REVERSED = "REVERSED"


class ReplayStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKER = "BLOCKER"


class ReconcileStatus(StrEnum):
    RUNNING = "RUNNING"
    CONVERGED = "CONVERGED"
    DIVERGED = "DIVERGED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


_EVENT_ID_RE = re.compile(r"^evt-(east|west)-g([0-9]{2,6})-([0-9]{6,18})$")
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{1,127}$")
_SUBJECT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_checksum(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def ensure_name(value: str, field_name: str) -> str:
    if not value or not _NAME_RE.fullmatch(value):
        raise ContractError(f"{field_name} has invalid value {value!r}")
    return value


def ensure_positive(value: int, field_name: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise ContractError(f"{field_name} must be >= {minimum}, got {value}")
    return value


def ensure_subject(subject: str, *, allow_wildcards: bool = True) -> str:
    if not subject:
        raise ContractError("subject cannot be empty")
    tokens = subject.split(".")
    for index, token in enumerate(tokens):
        if allow_wildcards and token == ">":
            if index != len(tokens) - 1:
                raise ContractError(f"terminal wildcard must be final token: {subject}")
            continue
        if allow_wildcards and token == "*":
            continue
        if not _SUBJECT_TOKEN_RE.fullmatch(token):
            raise ContractError(f"invalid NATS subject token {token!r} in {subject!r}")
    return subject


@dataclass(frozen=True, order=True)
class EventIdentity:
    region: str
    generation: int
    origin_sequence: int
    event_id: str

    def __post_init__(self) -> None:
        if self.region not in {"east", "west"}:
            raise ContractError(f"unsupported region {self.region!r}")
        ensure_positive(self.generation, "generation")
        ensure_positive(self.origin_sequence, "origin_sequence")
        match = _EVENT_ID_RE.fullmatch(self.event_id)
        if not match:
            raise ContractError(f"event_id does not follow stable identity format: {self.event_id!r}")
        id_region, id_generation, id_sequence = match.groups()
        if id_region != self.region:
            raise ContractError("event_id region disagrees with envelope region")
        if int(id_generation) != self.generation:
            raise ContractError("event_id generation disagrees with envelope generation")
        if int(id_sequence) != self.origin_sequence:
            raise ContractError("event_id sequence disagrees with envelope origin_sequence")

    @property
    def tuple_key(self) -> tuple[str, int, int, str]:
        return self.region, self.generation, self.origin_sequence, self.event_id

    @property
    def origin_key(self) -> tuple[str, int, int]:
        return self.region, self.generation, self.origin_sequence

    @property
    def message_id(self) -> str:
        return self.event_id

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class EventEnvelope:
    identity: EventIdentity
    device_id: str
    site_id: str
    event_type: str
    event_time: datetime
    accepted_at: datetime
    payload: Mapping[str, Any]
    payload_sha256: str
    payload_bytes: int
    priority: int

    def __post_init__(self) -> None:
        ensure_name(self.device_id, "device_id")
        ensure_name(self.site_id, "site_id")
        ensure_name(self.event_type, "event_type")
        ensure_positive(self.payload_bytes, "payload_bytes")
        if not 0 <= self.priority <= 9:
            raise ContractError("priority must be between 0 and 9")
        canonical = canonical_json(self.payload)
        observed_hash = sha256_text(canonical)
        if len(self.payload_sha256) != 64:
            raise ContractError("payload_sha256 must be a 64-character hex digest")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.payload_sha256):
            raise ContractError("payload_sha256 contains non-hexadecimal characters")
        if self.event_time.tzinfo is None or self.accepted_at.tzinfo is None:
            raise ContractError("event timestamps must be timezone-aware")
        if self.event_time > self.accepted_at + timedelta(minutes=5):
            raise ContractError("event_time is implausibly ahead of accepted_at")
        object.__setattr__(self, "payload_sha256", self.payload_sha256.lower())
        object.__setattr__(self, "_computed_payload_hash", observed_hash)

    @property
    def computed_payload_hash(self) -> str:
        return getattr(self, "_computed_payload_hash")

    @property
    def payload_hash_matches(self) -> bool:
        return self.payload_sha256 == self.computed_payload_hash

    @property
    def message_id(self) -> str:
        return self.identity.message_id

    @property
    def raw_subject(self) -> str:
        return f"telemetry.{self.identity.region}.{self.event_type}"

    @property
    def archive_subject(self) -> str:
        return f"telemetry.raw.{self.identity.region}.{self.event_type}"

    def headers(self) -> dict[str, str]:
        return {
            "Nats-Msg-Id": self.message_id,
            "X-Event-Id": self.identity.event_id,
            "X-Origin-Region": self.identity.region,
            "X-Origin-Generation": str(self.identity.generation),
            "X-Origin-Sequence": str(self.identity.origin_sequence),
            "X-Payload-SHA256": self.payload_sha256,
            "X-Device-Id": self.device_id,
            "X-Site-Id": self.site_id,
        }

    def wire_payload(self) -> bytes:
        document = {
            "event_id": self.identity.event_id,
            "region": self.identity.region,
            "origin_generation": self.identity.generation,
            "origin_sequence": self.identity.origin_sequence,
            "device_id": self.device_id,
            "site_id": self.site_id,
            "event_type": self.event_type,
            "event_time": to_iso(self.event_time),
            "accepted_at": to_iso(self.accepted_at),
            "payload": dict(self.payload),
            "payload_sha256": self.payload_sha256,
            "payload_bytes": self.payload_bytes,
            "priority": self.priority,
        }
        return canonical_json(document).encode("utf-8")

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.as_dict(),
            "device_id": self.device_id,
            "site_id": self.site_id,
            "event_type": self.event_type,
            "event_time": to_iso(self.event_time),
            "accepted_at": to_iso(self.accepted_at),
            "payload": dict(self.payload),
            "payload_sha256": self.payload_sha256,
            "payload_bytes": self.payload_bytes,
            "priority": self.priority,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EventEnvelope":
        identity_data = data.get("identity") or data
        identity = EventIdentity(
            region=str(identity_data["region"]),
            generation=int(identity_data.get("generation", identity_data.get("origin_generation"))),
            origin_sequence=int(identity_data["origin_sequence"]),
            event_id=str(identity_data["event_id"]),
        )
        event_time = parse_iso(data.get("event_time"))
        accepted_at = parse_iso(data.get("accepted_at"))
        if event_time is None or accepted_at is None:
            raise ContractError("event mapping is missing required timestamps")
        payload = data.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ContractError("payload must be a mapping")
        return cls(
            identity=identity,
            device_id=str(data["device_id"]),
            site_id=str(data["site_id"]),
            event_type=str(data["event_type"]),
            event_time=event_time,
            accepted_at=accepted_at,
            payload=dict(payload),
            payload_sha256=str(data["payload_sha256"]),
            payload_bytes=int(data["payload_bytes"]),
            priority=int(data["priority"]),
        )


@dataclass(frozen=True)
class StreamRef:
    name: str
    domain: str
    subjects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ensure_name(self.name, "stream name")
        ensure_name(self.domain, "JetStream domain")
        for subject in self.subjects:
            ensure_subject(subject)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "domain": self.domain, "subjects": list(self.subjects)}


@dataclass(frozen=True)
class SourceBinding:
    region: str
    origin: StreamRef
    destination_prefix: str

    def __post_init__(self) -> None:
        if self.region not in {"east", "west"}:
            raise ContractError(f"invalid source region {self.region!r}")
        ensure_subject(self.destination_prefix + ".>")

    def as_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "origin": self.origin.as_dict(),
            "destination_prefix": self.destination_prefix,
        }


@dataclass(frozen=True)
class StreamPolicy:
    retention: str
    storage: str
    replicas: int
    duplicate_window_seconds: int
    max_age_seconds: int
    allow_direct: bool = False
    deny_delete: bool = True
    deny_purge: bool = True

    def __post_init__(self) -> None:
        if self.retention not in {"limits", "interest", "workqueue"}:
            raise ContractError(f"unsupported retention policy {self.retention!r}")
        if self.storage not in {"file", "memory"}:
            raise ContractError(f"unsupported storage {self.storage!r}")
        if self.replicas not in {1, 3, 5}:
            raise ContractError("replicas must be one of 1, 3 or 5")
        ensure_positive(self.duplicate_window_seconds, "duplicate_window_seconds")
        ensure_positive(self.max_age_seconds, "max_age_seconds")

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class ConsumerPolicy:
    name: str
    required: bool
    filter_subject: str
    max_ack_pending: int
    ack_wait_seconds: int
    effect_type: str

    def __post_init__(self) -> None:
        ensure_name(self.name, "consumer name")
        ensure_subject(self.filter_subject)
        ensure_positive(self.max_ack_pending, "max_ack_pending")
        ensure_positive(self.ack_wait_seconds, "ack_wait_seconds")
        ensure_name(self.effect_type, "effect_type")

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class RetentionPolicy:
    journal_min_age_seconds: int
    stream_max_age_seconds: int
    maximum_disconnect_seconds: int
    maximum_replay_seconds: int
    safety_margin_seconds: int

    def __post_init__(self) -> None:
        ensure_positive(self.journal_min_age_seconds, "journal_min_age_seconds")
        ensure_positive(self.stream_max_age_seconds, "stream_max_age_seconds")
        ensure_positive(self.maximum_disconnect_seconds, "maximum_disconnect_seconds")
        ensure_positive(self.maximum_replay_seconds, "maximum_replay_seconds")
        ensure_positive(self.safety_margin_seconds, "safety_margin_seconds", allow_zero=True)

    @property
    def required_horizon_seconds(self) -> int:
        return self.maximum_disconnect_seconds + self.maximum_replay_seconds + self.safety_margin_seconds

    @property
    def stream_horizon_safe(self) -> bool:
        return self.stream_max_age_seconds >= self.required_horizon_seconds

    def as_dict(self) -> dict[str, Any]:
        result = dataclasses.asdict(self)
        result["required_horizon_seconds"] = self.required_horizon_seconds
        result["stream_horizon_safe"] = self.stream_horizon_safe
        return result


@dataclass(frozen=True)
class OriginGeneration:
    region: str
    generation: int
    stream_fingerprint: str
    first_sequence: int
    last_observed_sequence: int
    status: GenerationStatus
    detected_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.region not in {"east", "west"}:
            raise ContractError(f"unsupported region {self.region!r}")
        ensure_positive(self.generation, "generation")
        ensure_positive(self.first_sequence, "first_sequence", allow_zero=True)
        ensure_positive(self.last_observed_sequence, "last_observed_sequence", allow_zero=True)
        ensure_name(self.stream_fingerprint, "stream_fingerprint")
        if self.status is GenerationStatus.CONFIRMED and self.approved_at is None:
            raise ContractError("confirmed generation requires approved_at")

    def accepts_sequence(self, sequence: int) -> bool:
        ensure_positive(sequence, "sequence")
        return self.status is GenerationStatus.CONFIRMED and sequence >= self.first_sequence

    def as_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "generation": self.generation,
            "stream_fingerprint": self.stream_fingerprint,
            "first_sequence": self.first_sequence,
            "last_observed_sequence": self.last_observed_sequence,
            "status": self.status.value,
            "detected_at": to_iso(self.detected_at),
            "approved_by": self.approved_by,
            "approved_at": to_iso(self.approved_at),
        }


@dataclass(frozen=True)
class PublishAck:
    event_id: str
    stream: str
    sequence: int
    duplicate: bool
    acknowledged_at: datetime

    def __post_init__(self) -> None:
        ensure_name(self.stream, "ack stream")
        ensure_positive(self.sequence, "ack sequence")
        if not _EVENT_ID_RE.fullmatch(self.event_id):
            raise ContractError(f"invalid acknowledged event id {self.event_id!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "stream": self.stream,
            "sequence": self.sequence,
            "duplicate": self.duplicate,
            "acknowledged_at": to_iso(self.acknowledged_at),
        }


@dataclass(frozen=True)
class ArchiveRecord:
    identity: EventIdentity
    hub_stream_sequence: int
    payload_sha256: str
    archived_at: datetime
    source_stream: str
    source_domain: str
    duplicate_observation_count: int = 0

    def __post_init__(self) -> None:
        ensure_positive(self.hub_stream_sequence, "hub_stream_sequence")
        ensure_name(self.source_stream, "source_stream")
        ensure_name(self.source_domain, "source_domain")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.payload_sha256):
            raise ContractError("archive payload hash is invalid")
        ensure_positive(self.duplicate_observation_count, "duplicate_observation_count", allow_zero=True)

    def stable_key(self) -> str:
        i = self.identity
        return f"{i.region}:{i.generation}:{i.origin_sequence}:{i.event_id}:{self.payload_sha256.lower()}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.as_dict(),
            "hub_stream_sequence": self.hub_stream_sequence,
            "payload_sha256": self.payload_sha256.lower(),
            "archived_at": to_iso(self.archived_at),
            "source_stream": self.source_stream,
            "source_domain": self.source_domain,
            "duplicate_observation_count": self.duplicate_observation_count,
        }


@dataclass(frozen=True)
class ProcessingEffect:
    consumer_name: str
    identity: EventIdentity
    effect_key: str
    effect_type: str
    effect_payload: Mapping[str, Any]
    effect_sha256: str
    status: EffectStatus
    worker_id: str
    fence_epoch: int
    prepared_at: datetime
    committed_at: datetime | None = None

    def __post_init__(self) -> None:
        ensure_name(self.consumer_name, "consumer_name")
        ensure_name(self.effect_key, "effect_key")
        ensure_name(self.effect_type, "effect_type")
        ensure_name(self.worker_id, "worker_id")
        ensure_positive(self.fence_epoch, "fence_epoch", allow_zero=True)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.effect_sha256):
            raise ContractError("effect_sha256 is invalid")
        if self.status is EffectStatus.COMMITTED and self.committed_at is None:
            raise ContractError("committed effect requires committed_at")

    @property
    def idempotency_key(self) -> tuple[str, str]:
        return self.consumer_name, self.identity.event_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "consumer_name": self.consumer_name,
            "identity": self.identity.as_dict(),
            "effect_key": self.effect_key,
            "effect_type": self.effect_type,
            "effect_payload": dict(self.effect_payload),
            "effect_sha256": self.effect_sha256,
            "status": self.status.value,
            "worker_id": self.worker_id,
            "fence_epoch": self.fence_epoch,
            "prepared_at": to_iso(self.prepared_at),
            "committed_at": to_iso(self.committed_at),
        }


@dataclass(frozen=True)
class ConsumerCheckpoint:
    consumer_name: str
    region: str
    generation: int
    last_effect_sequence: int
    last_ack_sequence: int
    jetstream_ack_floor: int
    last_event_id: str | None
    updated_at: datetime

    def __post_init__(self) -> None:
        ensure_name(self.consumer_name, "consumer_name")
        if self.region not in {"east", "west"}:
            raise ContractError(f"invalid checkpoint region {self.region!r}")
        ensure_positive(self.generation, "generation")
        ensure_positive(self.last_effect_sequence, "last_effect_sequence", allow_zero=True)
        ensure_positive(self.last_ack_sequence, "last_ack_sequence", allow_zero=True)
        ensure_positive(self.jetstream_ack_floor, "jetstream_ack_floor", allow_zero=True)
        if self.last_event_id is not None and not _EVENT_ID_RE.fullmatch(self.last_event_id):
            raise ContractError("checkpoint last_event_id is invalid")

    @property
    def application_sequence(self) -> int:
        return min(self.last_effect_sequence, self.last_ack_sequence)

    @property
    def state_gap(self) -> int:
        return self.jetstream_ack_floor - self.last_effect_sequence

    @property
    def is_consistent(self) -> bool:
        return self.last_effect_sequence == self.last_ack_sequence == self.jetstream_ack_floor

    def as_dict(self) -> dict[str, Any]:
        return {
            "consumer_name": self.consumer_name,
            "region": self.region,
            "generation": self.generation,
            "last_effect_sequence": self.last_effect_sequence,
            "last_ack_sequence": self.last_ack_sequence,
            "jetstream_ack_floor": self.jetstream_ack_floor,
            "last_event_id": self.last_event_id,
            "updated_at": to_iso(self.updated_at),
            "application_sequence": self.application_sequence,
            "state_gap": self.state_gap,
            "consistent": self.is_consistent,
        }


@dataclass(frozen=True, order=True)
class ReplayRange:
    region: str
    generation: int
    start_sequence: int
    end_sequence: int

    def __post_init__(self) -> None:
        if self.region not in {"east", "west"}:
            raise ContractError(f"invalid replay region {self.region!r}")
        ensure_positive(self.generation, "generation")
        ensure_positive(self.start_sequence, "start_sequence")
        ensure_positive(self.end_sequence, "end_sequence")
        if self.end_sequence < self.start_sequence:
            raise ContractError("replay end_sequence cannot precede start_sequence")

    def overlaps(self, other: "ReplayRange") -> bool:
        if self.region != other.region or self.generation != other.generation:
            return False
        return self.start_sequence <= other.end_sequence and other.start_sequence <= self.end_sequence

    def contains(self, sequence: int) -> bool:
        return self.start_sequence <= sequence <= self.end_sequence

    @property
    def width(self) -> int:
        return self.end_sequence - self.start_sequence + 1

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class ReplayPlan:
    plan_id: str
    replay_range: ReplayRange
    status: ReplayStatus
    reason: str
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    fence_epoch: int | None = None
    event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ensure_name(self.plan_id, "plan_id")
        ensure_name(self.created_by, "created_by")
        if not self.reason.strip():
            raise ContractError("replay plan reason cannot be blank")
        if self.status in {ReplayStatus.APPROVED, ReplayStatus.RUNNING, ReplayStatus.COMPLETED}:
            if self.approved_at is None or not self.approved_by:
                raise ContractError("approved/running/completed replay plan requires approval metadata")
        if self.fence_epoch is not None:
            ensure_positive(self.fence_epoch, "fence_epoch")
        if len(self.event_ids) != len(set(self.event_ids)):
            raise ContractError("replay plan contains duplicate event identities")

    @property
    def active(self) -> bool:
        return self.status in {ReplayStatus.APPROVED, ReplayStatus.RUNNING}

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "range": self.replay_range.as_dict(),
            "status": self.status.value,
            "reason": self.reason,
            "created_by": self.created_by,
            "created_at": to_iso(self.created_at),
            "approved_by": self.approved_by,
            "approved_at": to_iso(self.approved_at),
            "fence_epoch": self.fence_epoch,
            "event_ids": list(self.event_ids),
        }


@dataclass(frozen=True)
class LeaseToken:
    region: str
    owner_id: str
    fence_epoch: int
    acquired_at: datetime
    renewed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.region not in {"east", "west"}:
            raise ContractError(f"invalid lease region {self.region!r}")
        ensure_name(self.owner_id, "owner_id")
        ensure_positive(self.fence_epoch, "fence_epoch")
        if self.expires_at <= self.renewed_at:
            raise ContractError("lease expiry must be after renewal time")

    def expired(self, at: datetime | None = None) -> bool:
        return (at or utcnow()) >= self.expires_at

    def assert_current(self, *, owner_id: str, fence_epoch: int, at: datetime | None = None) -> None:
        if owner_id != self.owner_id:
            raise FencingError(f"lease owner mismatch: expected {self.owner_id}, got {owner_id}")
        if fence_epoch != self.fence_epoch:
            raise FencingError(f"stale fence epoch: expected {self.fence_epoch}, got {fence_epoch}")
        if self.expired(at):
            raise FencingError("lease has expired")

    def as_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "owner_id": self.owner_id,
            "fence_epoch": self.fence_epoch,
            "acquired_at": to_iso(self.acquired_at),
            "renewed_at": to_iso(self.renewed_at),
            "expires_at": to_iso(self.expires_at),
        }


@dataclass(frozen=True)
class Finding:
    severity: FindingSeverity
    finding_type: str
    message: str
    region: str | None = None
    generation: int | None = None
    origin_sequence: int | None = None
    event_id: str | None = None
    expected_value: str | None = None
    observed_value: str | None = None
    remediation_hint: str | None = None

    def __post_init__(self) -> None:
        ensure_name(self.finding_type, "finding_type")
        if not self.message.strip():
            raise ContractError("finding message cannot be blank")
        if self.region is not None and self.region not in {"east", "west"}:
            raise ContractError("finding region is invalid")
        if self.generation is not None:
            ensure_positive(self.generation, "generation")
        if self.origin_sequence is not None:
            ensure_positive(self.origin_sequence, "origin_sequence")

    def stable_key(self) -> str:
        fields = [
            self.severity.value,
            self.finding_type,
            self.region or "",
            str(self.generation or 0),
            str(self.origin_sequence or 0),
            self.event_id or "",
            self.expected_value or "",
            self.observed_value or "",
        ]
        return "|".join(fields)

    def as_dict(self) -> dict[str, Any]:
        result = dataclasses.asdict(self)
        result["severity"] = self.severity.value
        return result


@dataclass(frozen=True)
class ReconciliationSummary:
    run_id: str
    status: ReconcileStatus
    journal_event_count: int
    archive_event_count: int
    missing_count: int
    unexpected_count: int
    duplicate_count: int
    metadata_mismatch_count: int
    consumer_lag_count: int
    highest_contiguous_archive_origin_sequence: int
    required_consumer_progress: Mapping[str, int]
    checksum: str
    findings: tuple[Finding, ...] = ()

    def __post_init__(self) -> None:
        ensure_name(self.run_id, "run_id")
        for name in (
            "journal_event_count",
            "archive_event_count",
            "missing_count",
            "unexpected_count",
            "duplicate_count",
            "metadata_mismatch_count",
            "consumer_lag_count",
        ):
            ensure_positive(getattr(self, name), name, allow_zero=True)
        ensure_positive(
            self.highest_contiguous_archive_origin_sequence,
            "highest_contiguous_archive_origin_sequence",
            allow_zero=True,
        )
        for consumer_name, sequence in self.required_consumer_progress.items():
            ensure_name(consumer_name, "required_consumer_progress consumer")
            ensure_positive(sequence, "required_consumer_progress sequence", allow_zero=True)
        if not re.fullmatch(r"[0-9a-f]{64}", self.checksum):
            raise ContractError("reconciliation checksum must be sha256 hex")

    @property
    def blocking_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity in {FindingSeverity.ERROR, FindingSeverity.BLOCKER})

    @property
    def converged(self) -> bool:
        return self.status is ReconcileStatus.CONVERGED and not self.blocking_findings

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "journal_event_count": self.journal_event_count,
            "archive_event_count": self.archive_event_count,
            "missing_count": self.missing_count,
            "unexpected_count": self.unexpected_count,
            "duplicate_count": self.duplicate_count,
            "metadata_mismatch_count": self.metadata_mismatch_count,
            "consumer_lag_count": self.consumer_lag_count,
            "highest_contiguous_archive_origin_sequence": self.highest_contiguous_archive_origin_sequence,
            "required_consumer_progress": dict(self.required_consumer_progress),
            "checksum": self.checksum,
            "findings": [finding.as_dict() for finding in self.findings],
            "converged": self.converged,
        }


@dataclass(frozen=True)
class HealthReport:
    generated_at: datetime
    topology_ok: bool
    generations_ok: bool
    publication_ok: bool
    archive_ok: bool
    consumers_ok: bool
    retention_ok: bool
    recovery_ok: bool
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return all(
            (
                self.topology_ok,
                self.generations_ok,
                self.publication_ok,
                self.archive_ok,
                self.consumers_ok,
                self.retention_ok,
                self.recovery_ok,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": to_iso(self.generated_at),
            "healthy": self.healthy,
            "topology_ok": self.topology_ok,
            "generations_ok": self.generations_ok,
            "publication_ok": self.publication_ok,
            "archive_ok": self.archive_ok,
            "consumers_ok": self.consumers_ok,
            "retention_ok": self.retention_ok,
            "recovery_ok": self.recovery_ok,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class Topology:
    edge_streams: Mapping[str, StreamRef]
    hub_archive: StreamRef
    sources: tuple[SourceBinding, ...]
    raw_archive_subjects: tuple[str, ...]
    derived_subject_prefix: str

    def __post_init__(self) -> None:
        if set(self.edge_streams) != {"east", "west"}:
            raise ContractError("topology must define east and west edge streams")
        if set(source.region for source in self.sources) != {"east", "west"}:
            raise ContractError("hub topology must source both east and west")
        names = [stream.name for stream in self.edge_streams.values()]
        names.append(self.hub_archive.name)
        if len(names) != len(set(names)):
            raise ContractError("physical stream names must be unique across connected domains")
        for region, stream in self.edge_streams.items():
            matching = [source for source in self.sources if source.region == region]
            if len(matching) != 1:
                raise ContractError(f"region {region} must have exactly one hub source binding")
            source = matching[0]
            if source.origin.name != stream.name or source.origin.domain != stream.domain:
                raise ContractError(f"hub source binding for {region} does not match the edge owner")
        for subject in self.raw_archive_subjects:
            ensure_subject(subject)
        ensure_subject(self.derived_subject_prefix + ".>")
        if self.hub_archive.subjects:
            raise ContractError("raw hub archive must be source-only and may not expose local listen subjects")
        for subject in self.raw_archive_subjects:
            if subject.startswith(self.derived_subject_prefix + "."):
                raise ContractError("derived subject space overlaps raw archive subject space")

    def source_for(self, region: str) -> SourceBinding:
        for source in self.sources:
            if source.region == region:
                return source
        raise ContractError(f"no source binding for region {region!r}")

    def stream_for(self, region: str) -> StreamRef:
        try:
            return self.edge_streams[region]
        except KeyError as exc:
            raise ContractError(f"no edge stream for region {region!r}") from exc

    def as_dict(self) -> dict[str, Any]:
        return {
            "edge_streams": {region: stream.as_dict() for region, stream in self.edge_streams.items()},
            "hub_archive": self.hub_archive.as_dict(),
            "sources": [source.as_dict() for source in self.sources],
            "raw_archive_subjects": list(self.raw_archive_subjects),
            "derived_subject_prefix": self.derived_subject_prefix,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Topology":
        edge_data = data.get("edge_streams")
        if not isinstance(edge_data, Mapping):
            raise ContractError("topology edge_streams must be a mapping")
        edge_streams: dict[str, StreamRef] = {}
        for region, stream_data in edge_data.items():
            if not isinstance(stream_data, Mapping):
                raise ContractError(f"edge stream {region!r} must be a mapping")
            edge_streams[str(region)] = StreamRef(
                name=str(stream_data["name"]),
                domain=str(stream_data["domain"]),
                subjects=tuple(str(s) for s in stream_data.get("subjects", ())),
            )
        hub_data = data.get("hub_archive")
        if not isinstance(hub_data, Mapping):
            raise ContractError("hub_archive must be a mapping")
        hub = StreamRef(
            name=str(hub_data["name"]),
            domain=str(hub_data["domain"]),
            subjects=tuple(str(s) for s in hub_data.get("subjects", ())),
        )
        source_values = data.get("sources", ())
        if not isinstance(source_values, Sequence):
            raise ContractError("sources must be a sequence")
        sources: list[SourceBinding] = []
        for source_data in source_values:
            if not isinstance(source_data, Mapping):
                raise ContractError("source binding must be a mapping")
            origin_data = source_data.get("origin")
            if not isinstance(origin_data, Mapping):
                raise ContractError("source origin must be a mapping")
            origin = StreamRef(
                name=str(origin_data["name"]),
                domain=str(origin_data["domain"]),
                subjects=tuple(str(s) for s in origin_data.get("subjects", ())),
            )
            sources.append(
                SourceBinding(
                    region=str(source_data["region"]),
                    origin=origin,
                    destination_prefix=str(source_data["destination_prefix"]),
                )
            )
        return cls(
            edge_streams=edge_streams,
            hub_archive=hub,
            sources=tuple(sources),
            raw_archive_subjects=tuple(str(v) for v in data.get("raw_archive_subjects", ())),
            derived_subject_prefix=str(data.get("derived_subject_prefix", "telemetry.derived")),
        )


def contiguous_floor(sequences: Iterable[int], *, start: int = 1) -> int:
    ordered = sorted(set(int(value) for value in sequences if int(value) >= start))
    expected = start
    for sequence in ordered:
        if sequence < expected:
            continue
        if sequence != expected:
            return expected - 1
        expected += 1
    return expected - 1


def collapse_ranges(sequences: Iterable[int], *, region: str, generation: int) -> tuple[ReplayRange, ...]:
    ordered = sorted(set(int(value) for value in sequences))
    if not ordered:
        return ()
    result: list[ReplayRange] = []
    start = previous = ordered[0]
    for sequence in ordered[1:]:
        if sequence == previous + 1:
            previous = sequence
            continue
        result.append(ReplayRange(region, generation, start, previous))
        start = previous = sequence
    result.append(ReplayRange(region, generation, start, previous))
    return tuple(result)


def assert_non_overlapping(ranges: Iterable[ReplayRange]) -> None:
    ordered = sorted(ranges)
    for index, current in enumerate(ordered):
        for other in ordered[index + 1 :]:
            if current.region != other.region or current.generation != other.generation:
                continue
            if current.overlaps(other):
                raise ReplayConflict(f"overlapping replay ranges: {current.as_dict()} and {other.as_dict()}")
            if other.start_sequence > current.end_sequence:
                break


def deterministic_effect_key(consumer_name: str, event_id: str) -> str:
    ensure_name(consumer_name, "consumer_name")
    if not _EVENT_ID_RE.fullmatch(event_id):
        raise ContractError("event_id is invalid for effect key")
    return f"{consumer_name}:{event_id}"


def deterministic_effect_hash(effect_type: str, event_id: str, payload: Mapping[str, Any]) -> str:
    ensure_name(effect_type, "effect_type")
    document = {"effect_type": effect_type, "event_id": event_id, "payload": dict(payload)}
    return sha256_text(canonical_json(document))


def report_checksum(archive_records: Iterable[ArchiveRecord]) -> str:
    keys = sorted(record.stable_key() for record in archive_records)
    return stable_checksum(keys)
