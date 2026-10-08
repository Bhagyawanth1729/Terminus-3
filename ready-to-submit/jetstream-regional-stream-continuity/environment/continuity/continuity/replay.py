"""Replay planning from missing identities."""

from __future__ import annotations

import uuid

from .model import ReplayConflict, ReplayRange, ReplayStatus, utcnow
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
        record = self.store.generation(region, generation)
        if record is None:
            return ReplayDecision(None, (), "unknown generation")
        missing = self.missing_event_ids(region, generation)
        if not missing:
            return ReplayDecision(None, (), None)
        all_events = list(self.store.iter_events(region=region, generation=generation))
        replay_range = ReplayRange(
            region,
            generation,
            min(event.identity.origin_sequence for event in all_events),
            max(event.identity.origin_sequence for event in all_events),
        )
        for active in self.store.active_replay_plans(region=region, generation=generation):
            if active.replay_range == replay_range:
                raise ReplayConflict(
                    f"an active replay plan already covers {replay_range.as_dict()}"
                )
        plan = self.store.insert_replay_plan(
            plan_id=f"rp-{region}-g{generation}-{uuid.uuid4().hex[:10]}",
            replay_range=replay_range,
            status=ReplayStatus.APPROVED if approve else ReplayStatus.DRAFT,
            reason=reason,
            created_by=created_by,
            event_ids=[event.identity.event_id for event in all_events],
            approved_by=approved_by if approve else None,
            approved_at=utcnow() if approve else None,
        )
        return ReplayDecision(plan, tuple(plan.event_ids), None)
