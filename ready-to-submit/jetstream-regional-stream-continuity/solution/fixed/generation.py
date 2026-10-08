"""Origin-generation observation and hold policy."""

from __future__ import annotations

import json

from .model import ContractError, to_iso
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
            self.store.execute(
                "INSERT INTO origin_observations(region,stream_name,domain,stream_fingerprint,first_sequence,last_sequence,observed_at,disposition,detail_json) "
                "VALUES(?,?,?,?,?,?,?,'PENDING_GENERATION',?)",
                (
                    observation.region,
                    observation.stream_name,
                    observation.domain,
                    observation.stream_fingerprint,
                    observation.first_sequence,
                    observation.last_sequence,
                    to_iso(observation.observed_at),
                    json.dumps({"generation": pending.generation}, sort_keys=True),
                ),
            )
            return pending

        same_fingerprint = observation.stream_fingerprint == current.stream_fingerprint
        sequence_regressed = observation.last_sequence < current.last_observed_sequence
        if same_fingerprint and not sequence_regressed:
            if observation.first_sequence > current.last_observed_sequence + 1:
                raise ContractError(
                    f"origin {observation.region} skipped from {current.last_observed_sequence} "
                    f"to {observation.first_sequence} without a generation transition"
                )
            self.store.update_generation_high_watermark(
                observation.region,
                current.generation,
                observation.last_sequence,
            )
            self.store.execute(
                "INSERT INTO origin_observations(region,stream_name,domain,stream_fingerprint,first_sequence,last_sequence,observed_at,disposition,detail_json) "
                "VALUES(?,?,?,?,?,?,?,'MATCH',?)",
                (
                    observation.region,
                    observation.stream_name,
                    observation.domain,
                    observation.stream_fingerprint,
                    observation.first_sequence,
                    observation.last_sequence,
                    to_iso(observation.observed_at),
                    json.dumps({"generation": current.generation}, sort_keys=True),
                ),
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
        elif pending.stream_fingerprint != observation.stream_fingerprint:
            raise ContractError(
                f"region {observation.region} has a different pending generation fingerprint"
            )
        else:
            self.store.update_generation_high_watermark(
                observation.region,
                pending.generation,
                observation.last_sequence,
            )
            pending = self.store.generation(observation.region, pending.generation)
            if pending is None:
                raise ContractError("pending generation disappeared")
        self.store.execute(
            "INSERT INTO origin_observations(region,stream_name,domain,stream_fingerprint,first_sequence,last_sequence,observed_at,disposition,detail_json) "
            "VALUES(?,?,?,?,?,?,?,'PENDING_GENERATION',?)",
            (
                observation.region,
                observation.stream_name,
                observation.domain,
                observation.stream_fingerprint,
                observation.first_sequence,
                observation.last_sequence,
                to_iso(observation.observed_at),
                json.dumps(
                    {
                        "generation": pending.generation,
                        "previous_generation": current.generation,
                        "operator_approval_required": True,
                        "sequence_regressed": sequence_regressed,
                    },
                    sort_keys=True,
                ),
            ),
        )
        return pending
