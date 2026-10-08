"""Replay planning from missing identities."""

from __future__ import annotations

import uuid

from .model import (
    GenerationStatus,
    ReplayConflict,
    ReplayRange,
    ReplayStatus,
    utcnow,
)
from .policy import ReplayDecision


class ReplayMixin:
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
        if generation_record.status is not GenerationStatus.CONFIRMED:
            return ReplayDecision(None, (), "origin generation requires operator approval")
        missing = self.missing_event_ids(region, generation)
        if not missing:
            return ReplayDecision(None, (), None)
        missing_events = [self.store.event_by_id(event_id) for event_id in missing]
        missing_events = [event for event in missing_events if event is not None]
        sequences = [event.identity.origin_sequence for event in missing_events]
        replay_range = ReplayRange(region, generation, min(sequences), max(sequences))
        for active in self.store.active_replay_plans(region=region, generation=generation):
            if active.replay_range.overlaps(replay_range):
                raise ReplayConflict(
                    f"active replay plan {active.plan_id} overlaps requested range {replay_range.as_dict()}"
                )
        status = ReplayStatus.APPROVED if approve else ReplayStatus.DRAFT
        plan = self.store.insert_replay_plan(
            plan_id=f"rp-{region}-g{generation}-{uuid.uuid4().hex[:10]}",
            replay_range=replay_range,
            status=status,
            reason=reason,
            created_by=created_by,
            event_ids=missing,
            approved_by=approved_by if approve else None,
            approved_at=utcnow() if approve else None,
        )
        return ReplayDecision(plan, missing, None)
