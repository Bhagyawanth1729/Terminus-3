from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .model import (
    ArchiveRecord,
    ConsumerCheckpoint,
    ContractError,
    EffectStatus,
    EventEnvelope,
    EventIdentity,
    Finding,
    FindingSeverity,
    GenerationStatus,
    LeaseToken,
    OriginGeneration,
    ProcessingEffect,
    PublishAck,
    PublishState,
    ReplayPlan,
    ReplayRange,
    ReplayStatus,
    canonical_json,
    deterministic_effect_hash,
    deterministic_effect_key,
    parse_iso,
    sha256_text,
    to_iso,
    utcnow,
)


@dataclass(frozen=True)
class ArchiveWatermark:
    region: str
    generation: int
    contiguous_sequence: int
    event_count: int
    maximum_sequence: int


@dataclass(frozen=True)
class RetentionWatermark:
    region: str
    generation: int
    archive_sequence: int
    slowest_required_consumer_sequence: int
    replay_pin_sequence: int | None
    cleanup_safe_sequence: int
    calculated_at: datetime


@dataclass(frozen=True)
class ReplayItem:
    plan_id: str
    event_id: str
    origin_sequence: int
    state: str
    attempts: int
    last_error: str | None
    updated_at: datetime


class ContinuityStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = self.connect()
            self._local.connection = connection
        return connection

    def close_thread_connection(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    @contextlib.contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        connection = self._connection()
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield connection
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self._connection().execute(sql, tuple(params))

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.execute(sql, params).fetchone()
        return None if row is None else row[0]

    def runtime_value(self, key: str, default: str | None = None) -> str | None:
        row = self.execute("SELECT value FROM runtime_kv WHERE key=?", (key,)).fetchone()
        return default if row is None else str(row["value"])

    def set_runtime_value(self, key: str, value: str, *, at: datetime | None = None) -> None:
        now = to_iso(at or utcnow())
        self.execute(
            "INSERT INTO runtime_kv(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (key, value, now),
        )

    def list_regions(self) -> list[dict[str, Any]]:
        rows = self.execute(
            "SELECT region,jetstream_domain,physical_stream,subject_prefix,required,enabled,created_at "
            "FROM regions ORDER BY region"
        ).fetchall()
        return [dict(row) for row in rows]

    def region(self, region: str) -> dict[str, Any]:
        row = self.execute(
            "SELECT region,jetstream_domain,physical_stream,subject_prefix,required,enabled,created_at "
            "FROM regions WHERE region=?",
            (region,),
        ).fetchone()
        if row is None:
            raise ContractError(f"unknown region {region!r}")
        return dict(row)

    def list_devices(self, *, region: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if region is not None:
            clauses.append("region=?")
            params.append(region)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.execute(
            "SELECT device_id,region,site_id,device_type,status,installed_at,criticality,last_seen_at "
            f"FROM device_registry{where} ORDER BY region,device_id",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def event_by_id(self, event_id: str) -> EventEnvelope | None:
        row = self.execute(
            "SELECT event_id,region,generation,origin_sequence,device_id,site_id,event_type,event_time,accepted_at,"
            "payload_json,payload_sha256,payload_bytes,priority FROM event_journal WHERE event_id=?",
            (event_id,),
        ).fetchone()
        return None if row is None else self._event_from_row(row)

    def event_by_origin(self, region: str, generation: int, origin_sequence: int) -> EventEnvelope | None:
        row = self.execute(
            "SELECT event_id,region,generation,origin_sequence,device_id,site_id,event_type,event_time,accepted_at,"
            "payload_json,payload_sha256,payload_bytes,priority FROM event_journal "
            "WHERE region=? AND generation=? AND origin_sequence=?",
            (region, generation, origin_sequence),
        ).fetchone()
        return None if row is None else self._event_from_row(row)

    def _event_from_row(self, row: sqlite3.Row) -> EventEnvelope:
        payload = json.loads(str(row["payload_json"]))
        return EventEnvelope(
            identity=EventIdentity(
                region=str(row["region"]),
                generation=int(row["generation"]),
                origin_sequence=int(row["origin_sequence"]),
                event_id=str(row["event_id"]),
            ),
            device_id=str(row["device_id"]),
            site_id=str(row["site_id"]),
            event_type=str(row["event_type"]),
            event_time=parse_iso(str(row["event_time"])) or utcnow(),
            accepted_at=parse_iso(str(row["accepted_at"])) or utcnow(),
            payload=payload,
            payload_sha256=str(row["payload_sha256"]),
            payload_bytes=int(row["payload_bytes"]),
            priority=int(row["priority"]),
        )

    def iter_events(
        self,
        *,
        region: str | None = None,
        generation: int | None = None,
        start_sequence: int | None = None,
        end_sequence: int | None = None,
        states: Sequence[PublishState | str] | None = None,
        limit: int | None = None,
    ) -> Iterator[EventEnvelope]:
        clauses: list[str] = []
        params: list[Any] = []
        if region is not None:
            clauses.append("region=?")
            params.append(region)
        if generation is not None:
            clauses.append("generation=?")
            params.append(generation)
        if start_sequence is not None:
            clauses.append("origin_sequence>=?")
            params.append(start_sequence)
        if end_sequence is not None:
            clauses.append("origin_sequence<=?")
            params.append(end_sequence)
        if states:
            state_values = [state.value if isinstance(state, PublishState) else str(state) for state in states]
            clauses.append("publish_state IN (%s)" % ",".join("?" for _ in state_values))
            params.extend(state_values)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT event_id,region,generation,origin_sequence,device_id,site_id,event_type,event_time,accepted_at,"
            "payload_json,payload_sha256,payload_bytes,priority FROM event_journal"
            f"{where} ORDER BY region,generation,origin_sequence"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cursor = self.execute(sql, params)
        for row in cursor:
            yield self._event_from_row(row)

    def journal_state(self, event_id: str) -> PublishState:
        value = self.scalar("SELECT publish_state FROM event_journal WHERE event_id=?", (event_id,))
        if value is None:
            raise ContractError(f"unknown event {event_id}")
        return PublishState(str(value))

    def journal_counts(self) -> dict[str, int]:
        rows = self.execute(
            "SELECT publish_state,COUNT(*) AS c FROM event_journal GROUP BY publish_state ORDER BY publish_state"
        ).fetchall()
        return {str(row["publish_state"]): int(row["c"]) for row in rows}

    def begin_publish_attempt(
        self,
        event_id: str,
        *,
        message_id: str,
        requested_stream: str,
        at: datetime | None = None,
    ) -> int:
        now = to_iso(at or utcnow())
        with self.transaction() as connection:
            event = connection.execute(
                "SELECT publish_state,publish_attempts FROM event_journal WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if event is None:
                raise ContractError(f"unknown event {event_id}")
            if str(event["publish_state"]) == PublishState.HELD.value:
                raise ContractError(f"event {event_id} is held and cannot be published")
            attempt_no = int(event["publish_attempts"]) + 1
            connection.execute(
                "INSERT INTO publish_attempts(event_id,attempt_no,message_id,requested_stream,started_at,outcome) "
                "VALUES(?,?,?,?,?,'STARTED')",
                (event_id, attempt_no, message_id, requested_stream, now),
            )
            connection.execute(
                "UPDATE event_journal SET publish_state='PUBLISHING',publish_attempts=?,last_publish_at=? WHERE event_id=?",
                (attempt_no, now, event_id),
            )
            return attempt_no

    def finish_publish_attempt(
        self,
        event_id: str,
        attempt_no: int,
        *,
        outcome: str,
        ack: PublishAck | None = None,
        error_code: str | None = None,
        error_text: str | None = None,
        at: datetime | None = None,
    ) -> None:
        if outcome not in {"ACKED", "TIMEOUT", "ERROR", "DUPLICATE_ACK"}:
            raise ContractError(f"invalid publish outcome {outcome!r}")
        now = to_iso(at or utcnow())
        with self.transaction() as connection:
            attempt = connection.execute(
                "SELECT message_id,requested_stream,outcome FROM publish_attempts WHERE event_id=? AND attempt_no=?",
                (event_id, attempt_no),
            ).fetchone()
            if attempt is None:
                raise ContractError(f"unknown publish attempt {event_id}/{attempt_no}")
            if str(attempt["outcome"]) != "STARTED":
                raise ContractError(f"publish attempt {event_id}/{attempt_no} is already terminal")
            if outcome in {"ACKED", "DUPLICATE_ACK"} and ack is None:
                raise ContractError("acknowledged outcome requires PublishAck")
            connection.execute(
                "UPDATE publish_attempts SET finished_at=?,outcome=?,ack_stream=?,ack_sequence=?,error_code=?,error_text=? "
                "WHERE event_id=? AND attempt_no=?",
                (
                    now,
                    outcome,
                    None if ack is None else ack.stream,
                    None if ack is None else ack.sequence,
                    error_code,
                    error_text,
                    event_id,
                    attempt_no,
                ),
            )
            if ack is not None:
                connection.execute(
                    "UPDATE event_journal SET publish_state='PUBLISHED',publish_ack_stream=?,publish_ack_sequence=?,last_publish_at=? "
                    "WHERE event_id=?",
                    (ack.stream, ack.sequence, now, event_id),
                )
            else:
                connection.execute(
                    "UPDATE event_journal SET publish_state='RETRY',last_publish_at=? WHERE event_id=?",
                    (now, event_id),
                )

    def publish_attempts(self, event_id: str) -> list[dict[str, Any]]:
        rows = self.execute(
            "SELECT attempt_no,message_id,requested_stream,started_at,finished_at,outcome,ack_stream,ack_sequence,error_code,error_text "
            "FROM publish_attempts WHERE event_id=? ORDER BY attempt_no",
            (event_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_held(self, event_id: str, *, reason: str) -> None:
        with self.transaction() as connection:
            connection.execute("UPDATE event_journal SET publish_state='HELD' WHERE event_id=?", (event_id,))
            connection.execute(
                "INSERT INTO operator_actions(action_type,region,generation,requested_by,requested_at,state,detail_json) "
                "SELECT 'EVENT_HOLD',region,generation,'controller',?,'REQUESTED',? FROM event_journal WHERE event_id=?",
                (to_iso(utcnow()), canonical_json({"event_id": event_id, "reason": reason}), event_id),
            )

    def confirmed_generation(self, region: str) -> OriginGeneration | None:
        row = self.execute(
            "SELECT region,generation,stream_fingerprint,first_sequence,last_observed_sequence,status,approved_by,approved_at,detected_at "
            "FROM origin_generations WHERE region=? AND status='CONFIRMED' ORDER BY generation DESC LIMIT 1",
            (region,),
        ).fetchone()
        return None if row is None else self._generation_from_row(row)

    def generation(self, region: str, generation: int) -> OriginGeneration | None:
        row = self.execute(
            "SELECT region,generation,stream_fingerprint,first_sequence,last_observed_sequence,status,approved_by,approved_at,detected_at "
            "FROM origin_generations WHERE region=? AND generation=?",
            (region, generation),
        ).fetchone()
        return None if row is None else self._generation_from_row(row)

    def _generation_from_row(self, row: sqlite3.Row) -> OriginGeneration:
        approved_at = parse_iso(row["approved_at"])
        return OriginGeneration(
            region=str(row["region"]),
            generation=int(row["generation"]),
            stream_fingerprint=str(row["stream_fingerprint"]),
            first_sequence=int(row["first_sequence"]),
            last_observed_sequence=int(row["last_observed_sequence"]),
            status=GenerationStatus(str(row["status"])),
            approved_by=None if row["approved_by"] is None else str(row["approved_by"]),
            approved_at=approved_at,
            detected_at=parse_iso(str(row["detected_at"])) or utcnow(),
        )

    def list_generations(self, region: str | None = None) -> list[OriginGeneration]:
        if region is None:
            rows = self.execute(
                "SELECT region,generation,stream_fingerprint,first_sequence,last_observed_sequence,status,approved_by,approved_at,detected_at "
                "FROM origin_generations ORDER BY region,generation"
            ).fetchall()
        else:
            rows = self.execute(
                "SELECT region,generation,stream_fingerprint,first_sequence,last_observed_sequence,status,approved_by,approved_at,detected_at "
                "FROM origin_generations WHERE region=? ORDER BY generation",
                (region,),
            ).fetchall()
        return [self._generation_from_row(row) for row in rows]

    def record_pending_generation(
        self,
        region: str,
        *,
        generation: int,
        stream_fingerprint: str,
        first_sequence: int,
        last_observed_sequence: int,
        at: datetime | None = None,
    ) -> OriginGeneration:
        detected = at or utcnow()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO origin_generations(region,generation,stream_fingerprint,first_sequence,last_observed_sequence,status,detected_at) "
                "VALUES(?,?,?,?,?,'PENDING_APPROVAL',?)",
                (
                    region,
                    generation,
                    stream_fingerprint,
                    first_sequence,
                    last_observed_sequence,
                    to_iso(detected),
                ),
            )
        value = self.generation(region, generation)
        if value is None:
            raise ContractError("failed to persist pending generation")
        return value

    def approve_generation(
        self,
        region: str,
        generation: int,
        *,
        approved_by: str,
        at: datetime | None = None,
    ) -> OriginGeneration:
        approved = at or utcnow()
        with self.transaction() as connection:
            pending = connection.execute(
                "SELECT status FROM origin_generations WHERE region=? AND generation=?",
                (region, generation),
            ).fetchone()
            if pending is None:
                raise ContractError(f"generation {region}/{generation} does not exist")
            if str(pending["status"]) != GenerationStatus.PENDING_APPROVAL.value:
                raise ContractError(f"generation {region}/{generation} is not pending approval")
            connection.execute(
                "UPDATE origin_generations SET status='RETIRED' WHERE region=? AND status='CONFIRMED'",
                (region,),
            )
            connection.execute(
                "UPDATE origin_generations SET status='CONFIRMED',approved_by=?,approved_at=? "
                "WHERE region=? AND generation=?",
                (approved_by, to_iso(approved), region, generation),
            )
            connection.execute(
                "INSERT INTO operator_actions(action_type,region,generation,requested_by,requested_at,approved_by,approved_at,state,detail_json) "
                "VALUES('APPROVE_GENERATION',?,?,?,?,?,?,'APPLIED',?)",
                (
                    region,
                    generation,
                    approved_by,
                    to_iso(approved),
                    approved_by,
                    to_iso(approved),
                    canonical_json({"region": region, "generation": generation}),
                ),
            )
        value = self.generation(region, generation)
        if value is None:
            raise ContractError("approved generation disappeared")
        return value

    def update_generation_high_watermark(self, region: str, generation: int, sequence: int) -> None:
        self.execute(
            "UPDATE origin_generations SET last_observed_sequence=MAX(last_observed_sequence,?) "
            "WHERE region=? AND generation=?",
            (sequence, region, generation),
        )

    def archive_record(self, event_id: str) -> ArchiveRecord | None:
        row = self.execute(
            "SELECT event_id,region,generation,origin_sequence,hub_stream_sequence,payload_sha256,archived_at,"
            "source_stream,source_domain,duplicate_observation_count FROM archive_index WHERE event_id=?",
            (event_id,),
        ).fetchone()
        return None if row is None else self._archive_from_row(row)

    def _archive_from_row(self, row: sqlite3.Row) -> ArchiveRecord:
        return ArchiveRecord(
            identity=EventIdentity(
                region=str(row["region"]),
                generation=int(row["generation"]),
                origin_sequence=int(row["origin_sequence"]),
                event_id=str(row["event_id"]),
            ),
            hub_stream_sequence=int(row["hub_stream_sequence"]),
            payload_sha256=str(row["payload_sha256"]),
            archived_at=parse_iso(str(row["archived_at"])) or utcnow(),
            source_stream=str(row["source_stream"]),
            source_domain=str(row["source_domain"]),
            duplicate_observation_count=int(row["duplicate_observation_count"]),
        )

    def iter_archive(
        self,
        *,
        region: str | None = None,
        generation: int | None = None,
        start_sequence: int | None = None,
        end_sequence: int | None = None,
    ) -> Iterator[ArchiveRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if region is not None:
            clauses.append("region=?")
            params.append(region)
        if generation is not None:
            clauses.append("generation=?")
            params.append(generation)
        if start_sequence is not None:
            clauses.append("origin_sequence>=?")
            params.append(start_sequence)
        if end_sequence is not None:
            clauses.append("origin_sequence<=?")
            params.append(end_sequence)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.execute(
            "SELECT event_id,region,generation,origin_sequence,hub_stream_sequence,payload_sha256,archived_at,"
            "source_stream,source_domain,duplicate_observation_count FROM archive_index"
            f"{where} ORDER BY region,generation,origin_sequence",
            params,
        )
        for row in rows:
            yield self._archive_from_row(row)

    def upsert_archive_record(self, record: ArchiveRecord) -> bool:
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT region,generation,origin_sequence,payload_sha256,duplicate_observation_count "
                "FROM archive_index WHERE event_id=?",
                (record.identity.event_id,),
            ).fetchone()
            if existing is not None:
                same_identity = (
                    str(existing["region"]) == record.identity.region
                    and int(existing["generation"]) == record.identity.generation
                    and int(existing["origin_sequence"]) == record.identity.origin_sequence
                )
                if not same_identity or str(existing["payload_sha256"]).lower() != record.payload_sha256.lower():
                    raise ContractError(f"archive identity collision for {record.identity.event_id}")
                connection.execute(
                    "UPDATE archive_index SET duplicate_observation_count=duplicate_observation_count+1 WHERE event_id=?",
                    (record.identity.event_id,),
                )
                return False
            connection.execute(
                "INSERT INTO archive_index(event_id,region,generation,origin_sequence,hub_stream_sequence,payload_sha256,"
                "archived_at,source_stream,source_domain,duplicate_observation_count) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    record.identity.event_id,
                    record.identity.region,
                    record.identity.generation,
                    record.identity.origin_sequence,
                    record.hub_stream_sequence,
                    record.payload_sha256.lower(),
                    to_iso(record.archived_at),
                    record.source_stream,
                    record.source_domain,
                    record.duplicate_observation_count,
                ),
            )
            connection.execute(
                "UPDATE event_journal SET publish_state='ARCHIVED',archive_confirmed_at=? WHERE event_id=?",
                (to_iso(record.archived_at), record.identity.event_id),
            )
            return True

    def archive_identity_set(self, region: str, generation: int) -> set[str]:
        rows = self.execute(
            "SELECT event_id FROM archive_index WHERE region=? AND generation=?",
            (region, generation),
        ).fetchall()
        return {str(row["event_id"]) for row in rows}

    def archive_origin_map(self, region: str, generation: int) -> dict[int, ArchiveRecord]:
        return {record.identity.origin_sequence: record for record in self.iter_archive(region=region, generation=generation)}

    def journal_origin_map(self, region: str, generation: int) -> dict[int, EventEnvelope]:
        return {event.identity.origin_sequence: event for event in self.iter_events(region=region, generation=generation)}

    def required_consumers(self) -> list[str]:
        rows = self.execute(
            "SELECT consumer_name FROM consumer_registry WHERE required=1 AND enabled=1 ORDER BY consumer_name"
        ).fetchall()
        return [str(row["consumer_name"]) for row in rows]

    def consumers(self) -> list[dict[str, Any]]:
        rows = self.execute(
            "SELECT consumer_name,required,stream_name,filter_subject,effect_type,max_ack_pending,ack_wait_seconds,enabled,created_at "
            "FROM consumer_registry ORDER BY consumer_name"
        ).fetchall()
        return [dict(row) for row in rows]

    def effect(self, consumer_name: str, event_id: str) -> ProcessingEffect | None:
        row = self.execute(
            "SELECT consumer_name,event_id,effect_key,region,generation,origin_sequence,effect_type,effect_payload,effect_sha256,"
            "status,prepared_at,committed_at,worker_id,fence_epoch FROM processing_effects "
            "WHERE consumer_name=? AND event_id=?",
            (consumer_name, event_id),
        ).fetchone()
        return None if row is None else self._effect_from_row(row)

    def _effect_from_row(self, row: sqlite3.Row) -> ProcessingEffect:
        return ProcessingEffect(
            consumer_name=str(row["consumer_name"]),
            identity=EventIdentity(
                region=str(row["region"]),
                generation=int(row["generation"]),
                origin_sequence=int(row["origin_sequence"]),
                event_id=str(row["event_id"]),
            ),
            effect_key=str(row["effect_key"]),
            effect_type=str(row["effect_type"]),
            effect_payload=json.loads(str(row["effect_payload"])),
            effect_sha256=str(row["effect_sha256"]),
            status=EffectStatus(str(row["status"])),
            worker_id=str(row["worker_id"]),
            fence_epoch=int(row["fence_epoch"]),
            prepared_at=parse_iso(str(row["prepared_at"])) or utcnow(),
            committed_at=parse_iso(row["committed_at"]),
        )

    def prepare_effect(
        self,
        *,
        consumer_name: str,
        event: EventEnvelope,
        effect_type: str,
        effect_payload: Mapping[str, Any],
        worker_id: str,
        fence_epoch: int,
        at: datetime | None = None,
    ) -> ProcessingEffect:
        now = at or utcnow()
        effect_key = deterministic_effect_key(consumer_name, event.identity.event_id)
        effect_hash = deterministic_effect_hash(effect_type, event.identity.event_id, effect_payload)
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT consumer_name,event_id,effect_key,region,generation,origin_sequence,effect_type,effect_payload,effect_sha256,"
                "status,prepared_at,committed_at,worker_id,fence_epoch FROM processing_effects "
                "WHERE consumer_name=? AND event_id=?",
                (consumer_name, event.identity.event_id),
            ).fetchone()
            if existing is not None:
                value = self._effect_from_row(existing)
                if value.effect_sha256 != effect_hash:
                    raise ContractError(f"idempotent effect payload changed for {consumer_name}/{event.identity.event_id}")
                return value
            connection.execute(
                "INSERT INTO processing_effects(consumer_name,event_id,effect_key,region,generation,origin_sequence,effect_type,"
                "effect_payload,effect_sha256,status,prepared_at,worker_id,fence_epoch) VALUES(?,?,?,?,?,?,?,?,?,'PREPARED',?,?,?)",
                (
                    consumer_name,
                    event.identity.event_id,
                    effect_key,
                    event.identity.region,
                    event.identity.generation,
                    event.identity.origin_sequence,
                    effect_type,
                    canonical_json(effect_payload),
                    effect_hash,
                    to_iso(now),
                    worker_id,
                    fence_epoch,
                ),
            )
        value = self.effect(consumer_name, event.identity.event_id)
        if value is None:
            raise ContractError("failed to persist prepared effect")
        return value

    def commit_effect(
        self,
        consumer_name: str,
        event_id: str,
        *,
        worker_id: str,
        fence_epoch: int,
        at: datetime | None = None,
    ) -> ProcessingEffect:
        now = at or utcnow()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status,worker_id,fence_epoch FROM processing_effects WHERE consumer_name=? AND event_id=?",
                (consumer_name, event_id),
            ).fetchone()
            if row is None:
                raise ContractError(f"effect does not exist: {consumer_name}/{event_id}")
            if str(row["status"]) == EffectStatus.COMMITTED.value:
                existing = self.effect(consumer_name, event_id)
                if existing is None:
                    raise ContractError("committed effect disappeared")
                return existing
            if str(row["status"]) != EffectStatus.PREPARED.value:
                raise ContractError(f"effect is not commit eligible: {row['status']}")
            connection.execute(
                "UPDATE processing_effects SET status='COMMITTED',committed_at=?,worker_id=?,fence_epoch=? "
                "WHERE consumer_name=? AND event_id=?",
                (to_iso(now), worker_id, fence_epoch, consumer_name, event_id),
            )
        result = self.effect(consumer_name, event_id)
        if result is None:
            raise ContractError("effect commit failed")
        return result

    def quarantine_effect(
        self,
        *,
        consumer_name: str,
        event: EventEnvelope,
        reason_code: str,
        reason_text: str,
        delivery_count: int,
        worker_id: str,
        fence_epoch: int,
        at: datetime | None = None,
    ) -> None:
        now = at or utcnow()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO poison_events(consumer_name,event_id,region,generation,origin_sequence,reason_code,reason_text,"
                "first_seen_at,last_seen_at,delivery_count,disposition) VALUES(?,?,?,?,?,?,?,?,?,?,'QUARANTINED') "
                "ON CONFLICT(consumer_name,event_id) DO UPDATE SET reason_code=excluded.reason_code,reason_text=excluded.reason_text,"
                "last_seen_at=excluded.last_seen_at,delivery_count=MAX(poison_events.delivery_count,excluded.delivery_count),"
                "disposition='QUARANTINED'",
                (
                    consumer_name,
                    event.identity.event_id,
                    event.identity.region,
                    event.identity.generation,
                    event.identity.origin_sequence,
                    reason_code,
                    reason_text,
                    to_iso(now),
                    to_iso(now),
                    delivery_count,
                ),
            )
            existing = connection.execute(
                "SELECT status FROM processing_effects WHERE consumer_name=? AND event_id=?",
                (consumer_name, event.identity.event_id),
            ).fetchone()
            if existing is None:
                effect_payload = {"quarantined": True, "reason_code": reason_code}
                connection.execute(
                    "INSERT INTO processing_effects(consumer_name,event_id,effect_key,region,generation,origin_sequence,effect_type,"
                    "effect_payload,effect_sha256,status,prepared_at,worker_id,fence_epoch) VALUES(?,?,?,?,?,?,?,?,?,'QUARANTINED',?,?,?)",
                    (
                        consumer_name,
                        event.identity.event_id,
                        deterministic_effect_key(consumer_name, event.identity.event_id),
                        event.identity.region,
                        event.identity.generation,
                        event.identity.origin_sequence,
                        "QUARANTINE",
                        canonical_json(effect_payload),
                        deterministic_effect_hash("QUARANTINE", event.identity.event_id, effect_payload),
                        to_iso(now),
                        worker_id,
                        fence_epoch,
                    ),
                )
            elif str(existing["status"]) != EffectStatus.COMMITTED.value:
                connection.execute(
                    "UPDATE processing_effects SET status='QUARANTINED',worker_id=?,fence_epoch=? "
                    "WHERE consumer_name=? AND event_id=?",
                    (worker_id, fence_epoch, consumer_name, event.identity.event_id),
                )

    def checkpoint(self, consumer_name: str, region: str, generation: int) -> ConsumerCheckpoint | None:
        row = self.execute(
            "SELECT consumer_name,region,generation,last_effect_sequence,last_ack_sequence,last_event_id,jetstream_ack_floor,updated_at "
            "FROM consumer_checkpoints WHERE consumer_name=? AND region=? AND generation=?",
            (consumer_name, region, generation),
        ).fetchone()
        return None if row is None else self._checkpoint_from_row(row)

    def _checkpoint_from_row(self, row: sqlite3.Row) -> ConsumerCheckpoint:
        return ConsumerCheckpoint(
            consumer_name=str(row["consumer_name"]),
            region=str(row["region"]),
            generation=int(row["generation"]),
            last_effect_sequence=int(row["last_effect_sequence"]),
            last_ack_sequence=int(row["last_ack_sequence"]),
            last_event_id=None if row["last_event_id"] is None else str(row["last_event_id"]),
            jetstream_ack_floor=int(row["jetstream_ack_floor"]),
            updated_at=parse_iso(str(row["updated_at"])) or utcnow(),
        )

    def checkpoints(self, consumer_name: str | None = None) -> list[ConsumerCheckpoint]:
        if consumer_name is None:
            rows = self.execute(
                "SELECT consumer_name,region,generation,last_effect_sequence,last_ack_sequence,last_event_id,jetstream_ack_floor,updated_at "
                "FROM consumer_checkpoints ORDER BY consumer_name,region,generation"
            ).fetchall()
        else:
            rows = self.execute(
                "SELECT consumer_name,region,generation,last_effect_sequence,last_ack_sequence,last_event_id,jetstream_ack_floor,updated_at "
                "FROM consumer_checkpoints WHERE consumer_name=? ORDER BY region,generation",
                (consumer_name,),
            ).fetchall()
        return [self._checkpoint_from_row(row) for row in rows]

    def advance_effect_checkpoint(
        self,
        *,
        consumer_name: str,
        identity: EventIdentity,
        at: datetime | None = None,
    ) -> ConsumerCheckpoint:
        now = to_iso(at or utcnow())
        with self.transaction() as connection:
            effect = connection.execute(
                "SELECT status FROM processing_effects WHERE consumer_name=? AND event_id=?",
                (consumer_name, identity.event_id),
            ).fetchone()
            if effect is None or str(effect["status"]) != EffectStatus.COMMITTED.value:
                raise ContractError("cannot advance effect checkpoint before committed effect")
            connection.execute(
                "INSERT INTO consumer_checkpoints(consumer_name,region,generation,last_effect_sequence,last_ack_sequence,last_event_id,"
                "jetstream_ack_floor,updated_at) VALUES(?,?,?,?,?,?,0,?) "
                "ON CONFLICT(consumer_name,region,generation) DO UPDATE SET "
                "last_effect_sequence=MAX(consumer_checkpoints.last_effect_sequence,excluded.last_effect_sequence),"
                "last_event_id=CASE WHEN excluded.last_effect_sequence>=consumer_checkpoints.last_effect_sequence THEN excluded.last_event_id ELSE consumer_checkpoints.last_event_id END,"
                "updated_at=excluded.updated_at",
                (
                    consumer_name,
                    identity.region,
                    identity.generation,
                    identity.origin_sequence,
                    0,
                    identity.event_id,
                    now,
                ),
            )
        checkpoint = self.checkpoint(consumer_name, identity.region, identity.generation)
        if checkpoint is None:
            raise ContractError("failed to persist effect checkpoint")
        return checkpoint

    def advance_ack_checkpoint(
        self,
        *,
        consumer_name: str,
        identity: EventIdentity,
        jetstream_ack_floor: int,
        at: datetime | None = None,
    ) -> ConsumerCheckpoint:
        now = to_iso(at or utcnow())
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO consumer_checkpoints(consumer_name,region,generation,last_effect_sequence,last_ack_sequence,last_event_id,"
                "jetstream_ack_floor,updated_at) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(consumer_name,region,generation) DO UPDATE SET "
                "last_ack_sequence=MAX(consumer_checkpoints.last_ack_sequence,excluded.last_ack_sequence),"
                "jetstream_ack_floor=MAX(consumer_checkpoints.jetstream_ack_floor,excluded.jetstream_ack_floor),"
                "last_event_id=CASE WHEN excluded.last_ack_sequence>=consumer_checkpoints.last_ack_sequence THEN excluded.last_event_id ELSE consumer_checkpoints.last_event_id END,"
                "updated_at=excluded.updated_at",
                (
                    consumer_name,
                    identity.region,
                    identity.generation,
                    0,
                    identity.origin_sequence,
                    identity.event_id,
                    jetstream_ack_floor,
                    now,
                ),
            )
        checkpoint = self.checkpoint(consumer_name, identity.region, identity.generation)
        if checkpoint is None:
            raise ContractError("failed to persist acknowledgement checkpoint")
        return checkpoint

    def set_jetstream_ack_floor(
        self,
        *,
        consumer_name: str,
        region: str,
        generation: int,
        ack_floor: int,
        at: datetime | None = None,
    ) -> None:
        now = to_iso(at or utcnow())
        self.execute(
            "INSERT INTO consumer_checkpoints(consumer_name,region,generation,last_effect_sequence,last_ack_sequence,last_event_id,"
            "jetstream_ack_floor,updated_at) VALUES(?,?,?,0,0,NULL,?,?) "
            "ON CONFLICT(consumer_name,region,generation) DO UPDATE SET jetstream_ack_floor=?,updated_at=?",
            (consumer_name, region, generation, ack_floor, now, ack_floor, now),
        )

    def create_reconciliation_run(self, *, mode: str, at: datetime | None = None) -> str:
        run_id = f"recon-{(at or utcnow()).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.execute(
            "INSERT INTO reconciliation_runs(run_id,started_at,mode,status) VALUES(?,?,?,'RUNNING')",
            (run_id, to_iso(at or utcnow()), mode),
        )
        return run_id

    def add_finding(self, run_id: str, finding: Finding, *, at: datetime | None = None) -> None:
        self.execute(
            "INSERT INTO reconciliation_findings(run_id,severity,region,generation,origin_sequence,event_id,finding_type,"
            "expected_value,observed_value,remediation_hint,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                finding.severity.value,
                finding.region,
                finding.generation,
                finding.origin_sequence,
                finding.event_id,
                finding.finding_type,
                finding.expected_value,
                finding.observed_value,
                finding.remediation_hint or finding.message,
                to_iso(at or utcnow()),
            ),
        )

    def findings(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.execute(
            "SELECT severity,region,generation,origin_sequence,event_id,finding_type,expected_value,observed_value,"
            "remediation_hint,created_at FROM reconciliation_findings WHERE run_id=? ORDER BY finding_id",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def finish_reconciliation_run(
        self,
        run_id: str,
        *,
        status: str,
        journal_event_count: int,
        archive_event_count: int,
        missing_count: int,
        duplicate_count: int,
        metadata_mismatch_count: int,
        consumer_lag_count: int,
        checksum: str,
        summary: Mapping[str, Any],
        at: datetime | None = None,
    ) -> None:
        self.execute(
            "UPDATE reconciliation_runs SET finished_at=?,status=?,archive_event_count=?,journal_event_count=?,missing_count=?,"
            "duplicate_count=?,metadata_mismatch_count=?,consumer_lag_count=?,checksum=?,summary_json=? WHERE run_id=?",
            (
                to_iso(at or utcnow()),
                status,
                archive_event_count,
                journal_event_count,
                missing_count,
                duplicate_count,
                metadata_mismatch_count,
                consumer_lag_count,
                checksum,
                canonical_json(summary),
                run_id,
            ),
        )

    def reconciliation_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.execute("SELECT * FROM reconciliation_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["findings"] = self.findings(run_id)
        if result.get("summary_json"):
            result["summary"] = json.loads(str(result["summary_json"]))
        return result

    def active_replay_plans(self, *, region: str | None = None, generation: int | None = None) -> list[ReplayPlan]:
        clauses = ["status IN ('APPROVED','RUNNING')"]
        params: list[Any] = []
        if region is not None:
            clauses.append("region=?")
            params.append(region)
        if generation is not None:
            clauses.append("generation=?")
            params.append(generation)
        rows = self.execute(
            "SELECT plan_id,region,generation,start_sequence,end_sequence,status,reason,created_by,created_at,approved_by,approved_at,fence_epoch "
            "FROM replay_plans WHERE " + " AND ".join(clauses) + " ORDER BY region,generation,start_sequence",
            params,
        ).fetchall()
        return [self._replay_plan_from_row(row) for row in rows]

    def replay_plan(self, plan_id: str) -> ReplayPlan | None:
        row = self.execute(
            "SELECT plan_id,region,generation,start_sequence,end_sequence,status,reason,created_by,created_at,approved_by,approved_at,fence_epoch "
            "FROM replay_plans WHERE plan_id=?",
            (plan_id,),
        ).fetchone()
        return None if row is None else self._replay_plan_from_row(row)

    def _replay_plan_from_row(self, row: sqlite3.Row) -> ReplayPlan:
        items = self.execute(
            "SELECT event_id FROM replay_plan_items WHERE plan_id=? ORDER BY origin_sequence,event_id",
            (row["plan_id"],),
        ).fetchall()
        return ReplayPlan(
            plan_id=str(row["plan_id"]),
            replay_range=ReplayRange(
                region=str(row["region"]),
                generation=int(row["generation"]),
                start_sequence=int(row["start_sequence"]),
                end_sequence=int(row["end_sequence"]),
            ),
            status=ReplayStatus(str(row["status"])),
            reason=str(row["reason"]),
            created_by=str(row["created_by"]),
            created_at=parse_iso(str(row["created_at"])) or utcnow(),
            approved_by=None if row["approved_by"] is None else str(row["approved_by"]),
            approved_at=parse_iso(row["approved_at"]),
            fence_epoch=None if row["fence_epoch"] is None else int(row["fence_epoch"]),
            event_ids=tuple(str(item["event_id"]) for item in items),
        )

    def insert_replay_plan(
        self,
        *,
        plan_id: str,
        replay_range: ReplayRange,
        status: ReplayStatus,
        reason: str,
        created_by: str,
        event_ids: Sequence[str],
        approved_by: str | None = None,
        approved_at: datetime | None = None,
        fence_epoch: int | None = None,
        at: datetime | None = None,
    ) -> ReplayPlan:
        now = at or utcnow()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO replay_plans(plan_id,region,generation,start_sequence,end_sequence,status,reason,created_by,created_at,"
                "approved_by,approved_at,fence_epoch) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    plan_id,
                    replay_range.region,
                    replay_range.generation,
                    replay_range.start_sequence,
                    replay_range.end_sequence,
                    status.value,
                    reason,
                    created_by,
                    to_iso(now),
                    approved_by,
                    to_iso(approved_at),
                    fence_epoch,
                ),
            )
            for event_id in event_ids:
                sequence = connection.execute(
                    "SELECT origin_sequence FROM event_journal WHERE event_id=? AND region=? AND generation=?",
                    (event_id, replay_range.region, replay_range.generation),
                ).fetchone()
                if sequence is None:
                    raise ContractError(f"replay event {event_id} is outside journal authority")
                origin_sequence = int(sequence["origin_sequence"])
                if not replay_range.contains(origin_sequence):
                    raise ContractError(f"replay event {event_id} lies outside declared range")
                connection.execute(
                    "INSERT INTO replay_plan_items(plan_id,event_id,origin_sequence,state,attempts,updated_at) "
                    "VALUES(?,?,?,'PENDING',0,?)",
                    (plan_id, event_id, origin_sequence, to_iso(now)),
                )
        value = self.replay_plan(plan_id)
        if value is None:
            raise ContractError("replay plan insert failed")
        return value

    def replay_items(self, plan_id: str) -> list[ReplayItem]:
        rows = self.execute(
            "SELECT plan_id,event_id,origin_sequence,state,attempts,last_error,updated_at FROM replay_plan_items "
            "WHERE plan_id=? ORDER BY origin_sequence,event_id",
            (plan_id,),
        ).fetchall()
        return [
            ReplayItem(
                plan_id=str(row["plan_id"]),
                event_id=str(row["event_id"]),
                origin_sequence=int(row["origin_sequence"]),
                state=str(row["state"]),
                attempts=int(row["attempts"]),
                last_error=None if row["last_error"] is None else str(row["last_error"]),
                updated_at=parse_iso(str(row["updated_at"])) or utcnow(),
            )
            for row in rows
        ]

    def update_replay_item(
        self,
        plan_id: str,
        event_id: str,
        *,
        state: str,
        error: str | None = None,
        increment_attempt: bool = False,
        at: datetime | None = None,
    ) -> None:
        if state not in {"PENDING", "PUBLISHED", "ALREADY_ARCHIVED", "FAILED", "HELD"}:
            raise ContractError(f"invalid replay item state {state}")
        self.execute(
            "UPDATE replay_plan_items SET state=?,last_error=?,attempts=attempts+?,updated_at=? WHERE plan_id=? AND event_id=?",
            (state, error, 1 if increment_attempt else 0, to_iso(at or utcnow()), plan_id, event_id),
        )

    def update_replay_status(
        self,
        plan_id: str,
        status: ReplayStatus,
        *,
        fence_epoch: int | None = None,
        at: datetime | None = None,
    ) -> None:
        now = to_iso(at or utcnow())
        started = now if status is ReplayStatus.RUNNING else None
        finished = now if status in {ReplayStatus.COMPLETED, ReplayStatus.FAILED, ReplayStatus.CANCELLED, ReplayStatus.BLOCKED} else None
        self.execute(
            "UPDATE replay_plans SET status=?,fence_epoch=COALESCE(?,fence_epoch),started_at=COALESCE(started_at,?),"
            "finished_at=COALESCE(?,finished_at) WHERE plan_id=?",
            (status.value, fence_epoch, started, finished, plan_id),
        )

    def current_lease(self, region: str) -> LeaseToken | None:
        row = self.execute(
            "SELECT region,owner_id,fence_epoch,acquired_at,renewed_at,expires_at FROM recovery_leases "
            "WHERE region=? AND released_at IS NULL",
            (region,),
        ).fetchone()
        if row is None:
            return None
        return LeaseToken(
            region=str(row["region"]),
            owner_id=str(row["owner_id"]),
            fence_epoch=int(row["fence_epoch"]),
            acquired_at=parse_iso(str(row["acquired_at"])) or utcnow(),
            renewed_at=parse_iso(str(row["renewed_at"])) or utcnow(),
            expires_at=parse_iso(str(row["expires_at"])) or utcnow(),
        )

    def write_lease(
        self,
        *,
        region: str,
        owner_id: str,
        fence_epoch: int,
        acquired_at: datetime,
        renewed_at: datetime,
        expires_at: datetime,
    ) -> LeaseToken:
        self.execute(
            "INSERT INTO recovery_leases(region,owner_id,fence_epoch,acquired_at,renewed_at,expires_at,released_at) "
            "VALUES(?,?,?,?,?,?,NULL) ON CONFLICT(region) DO UPDATE SET owner_id=excluded.owner_id,fence_epoch=excluded.fence_epoch,"
            "acquired_at=excluded.acquired_at,renewed_at=excluded.renewed_at,expires_at=excluded.expires_at,released_at=NULL",
            (
                region,
                owner_id,
                fence_epoch,
                to_iso(acquired_at),
                to_iso(renewed_at),
                to_iso(expires_at),
            ),
        )
        lease = self.current_lease(region)
        if lease is None:
            raise ContractError("failed to persist recovery lease")
        return lease

    def release_lease(self, region: str, *, owner_id: str, fence_epoch: int, at: datetime | None = None) -> None:
        lease = self.current_lease(region)
        if lease is None:
            return
        lease.assert_current(owner_id=owner_id, fence_epoch=fence_epoch, at=at or utcnow())
        self.execute(
            "UPDATE recovery_leases SET released_at=? WHERE region=? AND owner_id=? AND fence_epoch=?",
            (to_iso(at or utcnow()), region, owner_id, fence_epoch),
        )

    def retention_policy(self, region: str) -> dict[str, int]:
        row = self.execute(
            "SELECT journal_min_age_seconds,stream_max_age_seconds,maximum_disconnect_seconds,maximum_replay_seconds,safety_margin_seconds "
            "FROM retention_policies WHERE region=?",
            (region,),
        ).fetchone()
        if row is None:
            raise ContractError(f"no retention policy for region {region}")
        return {key: int(row[key]) for key in row.keys()}

    def retention_watermark(self, region: str, generation: int) -> RetentionWatermark | None:
        row = self.execute(
            "SELECT region,generation,archive_sequence,slowest_required_consumer_sequence,replay_pin_sequence,cleanup_safe_sequence,calculated_at "
            "FROM retention_watermarks WHERE region=? AND generation=?",
            (region, generation),
        ).fetchone()
        if row is None:
            return None
        return RetentionWatermark(
            region=str(row["region"]),
            generation=int(row["generation"]),
            archive_sequence=int(row["archive_sequence"]),
            slowest_required_consumer_sequence=int(row["slowest_required_consumer_sequence"]),
            replay_pin_sequence=None if row["replay_pin_sequence"] is None else int(row["replay_pin_sequence"]),
            cleanup_safe_sequence=int(row["cleanup_safe_sequence"]),
            calculated_at=parse_iso(str(row["calculated_at"])) or utcnow(),
        )

    def write_retention_watermark(self, watermark: RetentionWatermark) -> None:
        self.execute(
            "INSERT INTO retention_watermarks(region,generation,archive_sequence,slowest_required_consumer_sequence,replay_pin_sequence,"
            "cleanup_safe_sequence,calculated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(region,generation) DO UPDATE SET "
            "archive_sequence=excluded.archive_sequence,slowest_required_consumer_sequence=excluded.slowest_required_consumer_sequence,"
            "replay_pin_sequence=excluded.replay_pin_sequence,cleanup_safe_sequence=excluded.cleanup_safe_sequence,"
            "calculated_at=excluded.calculated_at",
            (
                watermark.region,
                watermark.generation,
                watermark.archive_sequence,
                watermark.slowest_required_consumer_sequence,
                watermark.replay_pin_sequence,
                watermark.cleanup_safe_sequence,
                to_iso(watermark.calculated_at),
            ),
        )

    def cleanup_candidate_ids(
        self,
        *,
        region: str,
        generation: int,
        safe_sequence: int,
        minimum_age_seconds: int,
        at: datetime | None = None,
        limit: int = 1000,
    ) -> list[str]:
        cutoff = (at or utcnow()) - timedelta(seconds=minimum_age_seconds)
        rows = self.execute(
            "SELECT event_id FROM event_journal WHERE region=? AND generation=? AND origin_sequence<=? AND retention_hold=0 "
            "AND accepted_at<=? ORDER BY origin_sequence LIMIT ?",
            (region, generation, safe_sequence, to_iso(cutoff), limit),
        ).fetchall()
        return [str(row["event_id"]) for row in rows]

    def set_retention_hold(self, event_ids: Sequence[str], *, held: bool) -> int:
        if not event_ids:
            return 0
        placeholders = ",".join("?" for _ in event_ids)
        cursor = self.execute(
            f"UPDATE event_journal SET retention_hold=? WHERE event_id IN ({placeholders})",
            [1 if held else 0, *event_ids],
        )
        return int(cursor.rowcount)

    def archive_count(self, region: str | None = None) -> int:
        if region is None:
            return int(self.scalar("SELECT COUNT(*) FROM archive_index") or 0)
        return int(self.scalar("SELECT COUNT(*) FROM archive_index WHERE region=?", (region,)) or 0)

    def journal_count(self, region: str | None = None) -> int:
        if region is None:
            return int(self.scalar("SELECT COUNT(*) FROM event_journal") or 0)
        return int(self.scalar("SELECT COUNT(*) FROM event_journal WHERE region=?", (region,)) or 0)

    def highest_journal_sequence(self, region: str, generation: int) -> int:
        return int(
            self.scalar(
                "SELECT COALESCE(MAX(origin_sequence),0) FROM event_journal WHERE region=? AND generation=?",
                (region, generation),
            )
            or 0
        )

    def highest_archive_sequence(self, region: str, generation: int) -> int:
        return int(
            self.scalar(
                "SELECT COALESCE(MAX(origin_sequence),0) FROM archive_index WHERE region=? AND generation=?",
                (region, generation),
            )
            or 0
        )

    def slowest_required_consumer_sequence(self, region: str, generation: int) -> int:
        consumers = self.required_consumers()
        if not consumers:
            return self.highest_archive_sequence(region, generation)
        values: list[int] = []
        for consumer in consumers:
            checkpoint = self.checkpoint(consumer, region, generation)
            values.append(0 if checkpoint is None else checkpoint.application_sequence)
        return min(values)

    def first_active_replay_sequence(self, region: str, generation: int) -> int | None:
        value = self.scalar(
            "SELECT MIN(start_sequence) FROM replay_plans WHERE region=? AND generation=? AND status IN ('APPROVED','RUNNING')",
            (region, generation),
        )
        return None if value is None else int(value)

    def operator_action(
        self,
        *,
        action_type: str,
        requested_by: str,
        detail: Mapping[str, Any],
        region: str | None = None,
        generation: int | None = None,
        state: str = "REQUESTED",
        at: datetime | None = None,
    ) -> int:
        cursor = self.execute(
            "INSERT INTO operator_actions(action_type,region,generation,requested_by,requested_at,state,detail_json) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                action_type,
                region,
                generation,
                requested_by,
                to_iso(at or utcnow()),
                state,
                canonical_json(detail),
            ),
        )
        return int(cursor.lastrowid)

    def state_digest(self) -> str:
        parts: list[str] = []
        for table, order_by in (
            ("origin_generations", "region,generation"),
            ("archive_index", "region,generation,origin_sequence,event_id"),
            ("consumer_checkpoints", "consumer_name,region,generation"),
            ("processing_effects", "consumer_name,event_id"),
            ("replay_plans", "plan_id"),
            ("recovery_leases", "region"),
            ("retention_watermarks", "region,generation"),
        ):
            rows = self.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()
            for row in rows:
                parts.append(table + ":" + canonical_json(dict(row)))
        return sha256_text("\n".join(parts))
