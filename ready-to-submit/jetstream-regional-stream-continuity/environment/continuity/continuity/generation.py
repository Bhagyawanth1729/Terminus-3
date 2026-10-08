"""Origin-generation observation and hold policy."""

from __future__ import annotations

from .model import ContractError
from .policy import OriginObservation


class GenerationMixin:
    def validate_origin_observation(self, observation: OriginObservation):
        region_cfg = self.region_config(observation.region)
        expected_stream = str(region_cfg["stream_name"])
        expected_domain = str(region_cfg["domain"])
        if observation.stream_name != expected_stream:
            raise ContractError(
                f"observed stream {observation.stream_name} does not match configured {expected_stream}"
            )
        if observation.domain != expected_domain:
            raise ContractError(
                f"observed domain {observation.domain} does not match configured {expected_domain}"
            )
        current = self.store.confirmed_generation(observation.region)
        if current is None:
            pending = self.store.record_pending_generation(
                observation.region,
                generation=1,
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
