"""Journal cleanup watermarks."""

from __future__ import annotations

from datetime import datetime

from .model import contiguous_floor, utcnow
from .policy import RetentionDecision
from .store import RetentionWatermark


class RetentionMixin:
    def compute_retention_decision(
        self,
        *,
        region: str,
        generation: int,
        at: datetime | None = None,
        limit: int = 1000,
    ) -> RetentionDecision:
        policy = self.retention_policy(region)
        archive_sequences = [
            record.identity.origin_sequence
            for record in self.store.iter_archive(region=region, generation=generation)
        ]
        archive_sequence = contiguous_floor(archive_sequences)
        consumer_sequence = self.store.slowest_required_consumer_sequence(region, generation)
        replay_pin = self.store.first_active_replay_sequence(region, generation)
        candidates_for_min = [archive_sequence, consumer_sequence]
        if replay_pin is not None:
            candidates_for_min.append(max(replay_pin - 1, 0))
        safe_sequence = min(candidates_for_min) if candidates_for_min else 0
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
        event_ids = self.store.cleanup_candidate_ids(
            region=region,
            generation=generation,
            safe_sequence=safe_sequence,
            minimum_age_seconds=max(
                policy.journal_min_age_seconds,
                policy.required_horizon_seconds,
            ),
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
            eligible_event_ids=tuple(event_ids),
            horizon_safe=policy.stream_horizon_safe,
        )
