"""Publish path for accepted journal events."""

from __future__ import annotations

from .model import ContractError, EventEnvelope, PublishAck
from .policy import Publisher


class PublishMixin:
    def message_id_for_event(self, event: EventEnvelope, *, attempt_no: int) -> str:
        return event.identity.event_id

    async def publish_event(self, event_id: str, publisher: Publisher) -> PublishAck:
        event = self.store.event_by_id(event_id)
        if event is None:
            raise ContractError(f"event {event_id} is not in the edge journal")
        expected_stream = self.expected_stream_for_event(event)
        attempt_no = self._next_attempt(event.identity.event_id)
        message_id = self.message_id_for_event(event, attempt_no=attempt_no)
        attempt_no = self.store.begin_publish_attempt(
            event.identity.event_id,
            message_id=message_id,
            requested_stream=expected_stream,
        )
        try:
            ack = await publisher.publish(
                event, message_id=message_id, expected_stream=expected_stream
            )
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
        if ack.stream != expected_stream:
            message = (
                f"publish acknowledgement stream {ack.stream} does not match "
                f"expected {expected_stream}"
            )
            self.store.finish_publish_attempt(
                event.identity.event_id,
                attempt_no,
                outcome="ERROR",
                error_code="ACK_STREAM_MISMATCH",
                error_text=message,
            )
            raise ContractError(message)
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
