"""Journal cleanup watermarks."""

from __future__ import annotations

from datetime import datetime

from .policy import RetentionDecision
from .store import RetentionWatermark
from .model import utcnow


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
        archive_sequence = self.store.highest_archive_sequence(region, generation)
        consumer_sequence = self.store.slowest_required_consumer_sequence(region, generation)
        replay_pin = self.store.first_active_replay_sequence(region, generation)
        safe_sequence = archive_sequence
        self.store.write_retention_watermark(
            RetentionWatermark(
                region=region,
                generation=generation,
                archive_sequence=archive_sequence,
                slowest_required_consumer_sequence=consumer_sequence,
                replay_pin_sequence=replay_pin,
                cleanup_safe_sequence=safe_sequence,
                calculated_at=at or utcnow(),
            )
        )
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
