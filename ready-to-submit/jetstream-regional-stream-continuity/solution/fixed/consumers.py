"""Durable consumer effect and checkpoint handling."""

from __future__ import annotations

import asyncio
import json
import urllib.request
from collections.abc import Mapping
from typing import Any

from .model import ContractError, EffectStatus, EventEnvelope, to_iso, utcnow
from .policy import Delivery, ProcessingResult


class ConsumerMixin:
    def _device_status(self, device_id: str) -> str | None:
        row = self.store.execute(
            "SELECT status FROM device_registry WHERE device_id=?",
            (device_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row["status"])

    def _dispatch_count(self, consumer_name: str, event_id: str) -> int:
        value = self.store.scalar(
            "SELECT COUNT(*) FROM effect_dispatches WHERE consumer_name=? AND event_id=? AND state='CONFIRMED'",
            (consumer_name, event_id),
        )
        return int(value or 0)

    def _emit_dispatch_once(
        self,
        *,
        consumer_name: str,
        event: EventEnvelope,
        worker_id: str,
        fence_epoch: int,
        detail: Mapping[str, Any],
    ) -> bool:
        if self._dispatch_count(consumer_name, event.identity.event_id) > 0:
            return False
        consumer = next(
            (
                row
                for row in self.store.consumers()
                if str(row["consumer_name"]) == consumer_name
            ),
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
        return True

    def _should_quarantine(self, event: EventEnvelope) -> bool:
        status = self._device_status(event.device_id)
        return status == "QUARANTINED"

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
        poison = self._should_quarantine(event)
        if poison_predicate is not None:
            poison = poison or bool(poison_predicate(event))
        if poison:
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
            self.store.set_jetstream_ack_floor(
                consumer_name=delivery.consumer_name,
                region=event.identity.region,
                generation=event.identity.generation,
                ack_floor=delivery.jetstream_ack_floor,
            )
            return ProcessingResult(
                consumer_name=delivery.consumer_name,
                event_id=event.identity.event_id,
                status="QUARANTINED",
                duplicate_effect=False,
                checkpoint=self.store.checkpoint(
                    delivery.consumer_name,
                    event.identity.region,
                    event.identity.generation,
                ),
                detail={
                    "delivery_count": delivery.delivery_count,
                    "effect_complete": False,
                },
            )

        existing = self.store.effect(delivery.consumer_name, event.identity.event_id)
        duplicate_effect = (
            existing is not None and existing.status is EffectStatus.COMMITTED
        )
        payload = self._consumer_effect_payload(delivery.consumer_name, event)
        if not duplicate_effect:
            effect = self.store.prepare_effect(
                consumer_name=delivery.consumer_name,
                event=event,
                effect_type=self._consumer_effect_type(delivery.consumer_name),
                effect_payload=payload,
                worker_id=worker_id,
                fence_epoch=fence_epoch,
            )
            self._emit_dispatch_once(
                consumer_name=delivery.consumer_name,
                event=event,
                worker_id=worker_id,
                fence_epoch=fence_epoch,
                detail=payload,
            )
            if effect.status is not EffectStatus.COMMITTED:
                self.store.commit_effect(
                    delivery.consumer_name,
                    event.identity.event_id,
                    worker_id=worker_id,
                    fence_epoch=fence_epoch,
                )
        else:
            self._emit_dispatch_once(
                consumer_name=delivery.consumer_name,
                event=event,
                worker_id=worker_id,
                fence_epoch=fence_epoch,
                detail=payload,
            )
        checkpoint = self.store.advance_effect_checkpoint(
            consumer_name=delivery.consumer_name,
            identity=event.identity,
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
            status="COMMITTED",
            duplicate_effect=duplicate_effect,
            checkpoint=checkpoint,
            detail={
                "delivery_count": delivery.delivery_count,
                "worker_id": worker_id,
                "dispatch_count": self._dispatch_count(
                    delivery.consumer_name,
                    event.identity.event_id,
                ),
            },
        )

    def derived_subject_for(self, event: EventEnvelope, *, consumer_name: str) -> str:
        prefix = str(
            self.config.get("topology", {}).get("derived_subject_prefix", "telemetry.derived")
        )
        safe_consumer = consumer_name.replace("_", "-")
        return f"{prefix}.{event.identity.region}.{safe_consumer}.{event.event_type}"

    def consumer_health(self) -> tuple[bool, dict[str, Any]]:
        details: dict[str, Any] = {}
        ok = True
        for consumer_name in self.store.required_consumers():
            checkpoints = self.store.checkpoints(consumer_name)
            details[consumer_name] = [checkpoint.as_dict() for checkpoint in checkpoints]
            for checkpoint in checkpoints:
                if not checkpoint.is_consistent:
                    ok = False

        hub = self.config.get("hub")
        if not isinstance(hub, Mapping):
            return ok, details
        monitor_url = str(hub.get("monitor_url", "")).rstrip("/")
        if not monitor_url:
            return ok, details
        try:
            with urllib.request.urlopen(monitor_url + "/varz", timeout=0.2) as response:
                response.read(1)
        except Exception:
            return ok, details

        async def observe() -> dict[str, tuple[str, int, int]]:
            from .runtime import JetStreamAdmin, NatsConnectionPool, endpoints_from_engine

            observed: dict[str, tuple[str, int, int]] = {}
            pool = NatsConnectionPool()
            try:
                admin = JetStreamAdmin(pool, endpoints_from_engine(self))
                stream_name = self.topology().hub_archive.name
                for consumer_name in self.store.required_consumers():
                    try:
                        info = await admin.consumer_info("hub", stream_name, consumer_name)
                    except Exception:
                        continue
                    if info.ack_floor_stream_sequence <= 0:
                        continue
                    try:
                        message = await admin.get_message_by_sequence(
                            "hub",
                            stream_name,
                            info.ack_floor_stream_sequence,
                        )
                        document = json.loads(message.data.decode("utf-8"))
                        observed[consumer_name] = (
                            str(document["region"]),
                            int(
                                document.get(
                                    "origin_generation",
                                    document.get("generation"),
                                )
                            ),
                            int(document["origin_sequence"]),
                        )
                    except Exception:
                        continue
                return observed
            finally:
                await pool.close()

        try:
            external = asyncio.run(observe())
        except Exception:
            external = {}
        for consumer_name, (region, generation, sequence) in external.items():
            checkpoint = self.store.checkpoint(consumer_name, region, generation)
            if checkpoint is None or checkpoint.application_sequence != sequence:
                ok = False
            details.setdefault(consumer_name, []).append(
                {
                    "external_region": region,
                    "external_generation": generation,
                    "external_origin_sequence": sequence,
                }
            )
        return ok, details
