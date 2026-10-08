"""Durable consumer effect and checkpoint handling."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .model import ContractError, EffectStatus, EventEnvelope, to_iso, utcnow
from .policy import Delivery, ProcessingResult


class ConsumerMixin:
    def _emit_dispatch(
        self,
        *,
        consumer_name: str,
        event: EventEnvelope,
        worker_id: str,
        fence_epoch: int,
        detail: Mapping[str, Any],
    ) -> None:
        consumer = next(
            (row for row in self.store.consumers() if str(row["consumer_name"]) == consumer_name),
            None,
        )
        if consumer is None:
            raise ContractError(f"unknown consumer {consumer_name}")
        self.store.execute(
            "INSERT INTO effect_dispatches(consumer_name,event_id,effect_key,effect_type,dispatched_at,worker_id,fence_epoch,state,detail_json) "
            "VALUES(?,?,?,?,?,?,?,'CONFIRMED',?)",
            (
                consumer_name,
                event.identity.event_id,
                f"{consumer_name}:{event.identity.event_id}",
                str(consumer["effect_type"]),
                to_iso(utcnow()),
                worker_id,
                fence_epoch,
                json.dumps(dict(detail), sort_keys=True, separators=(",", ":")),
            ),
        )

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
        payload = self._consumer_effect_payload(delivery.consumer_name, event)
        self._emit_dispatch(
            consumer_name=delivery.consumer_name,
            event=event,
            worker_id=worker_id,
            fence_epoch=fence_epoch,
            detail=payload,
        )
        if not duplicate_effect:
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

    def derived_subject_for(self, event: EventEnvelope, *, consumer_name: str) -> str:
        return f"telemetry.raw.{event.identity.region}.{consumer_name}.{event.event_type}"

    def consumer_health(self) -> tuple[bool, dict[str, Any]]:
        details: dict[str, Any] = {}
        for consumer_name in self.store.required_consumers():
            checkpoints = self.store.checkpoints(consumer_name)
            details[consumer_name] = [checkpoint.as_dict() for checkpoint in checkpoints]
        return True, details
