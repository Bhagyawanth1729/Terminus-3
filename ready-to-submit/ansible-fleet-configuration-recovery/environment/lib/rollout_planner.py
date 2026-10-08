from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from inventory_model import FleetModel, HostIdentity, partition_by_site, select_hosts


class RolloutError(ValueError):
    pass


class HostStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class HostOutcome:
    host: str
    target_revision: str
    status: HostStatus = HostStatus.PENDING
    applied_revision: str = ""
    attempt: int = 0
    message: str = ""

    def at_target(self) -> bool:
        return self.status == HostStatus.SUCCEEDED and self.applied_revision == self.target_revision

    def retryable(self, max_attempts: int) -> bool:
        return self.status in {HostStatus.FAILED, HostStatus.BLOCKED} and self.attempt < max_attempts


@dataclass(frozen=True)
class RolloutWave:
    index: int
    hosts: tuple[str, ...]
    canary: bool = False
    required_successes: int = 0
    max_failures: int = 0

    def __post_init__(self) -> None:
        if self.index < 0:
            raise RolloutError("wave index cannot be negative")
        if not self.hosts:
            raise RolloutError("rollout wave cannot be empty")
        if len(set(self.hosts)) != len(self.hosts):
            raise RolloutError("rollout wave contains duplicate hosts")
        if self.required_successes < 0 or self.required_successes > len(self.hosts):
            raise RolloutError("invalid required_successes")
        if self.max_failures < 0 or self.max_failures > len(self.hosts):
            raise RolloutError("invalid max_failures")


@dataclass(frozen=True)
class RolloutPlan:
    revision: str
    waves: tuple[RolloutWave, ...]
    max_attempts: int = 2
    failure_budget: int = 1
    metadata: Mapping[str, str] = field(default_factory=dict)

    def hosts(self) -> tuple[str, ...]:
        return tuple(host for wave in self.waves for host in wave.hosts)

    def wave(self, index: int) -> RolloutWave:
        for wave in self.waves:
            if wave.index == index:
                return wave
        raise RolloutError(f"unknown wave {index}")


@dataclass(frozen=True)
class RolloutState:
    revision: str
    outcomes: Mapping[str, HostOutcome]
    active_wave: int = 0
    halted: bool = False
    halt_reason: str = ""

    def outcome(self, host: str) -> HostOutcome:
        if host not in self.outcomes:
            raise RolloutError(f"host {host} is not part of rollout")
        return self.outcomes[host]


@dataclass(frozen=True)
class ProgressDecision:
    advance: bool
    halt: bool
    reason: str
    next_wave: int | None


def _ordered_hosts(hosts: Iterable[HostIdentity]) -> tuple[HostIdentity, ...]:
    return tuple(sorted(hosts, key=lambda host: (host.site, host.zone, host.name)))


def _round_robin_site_hosts(hosts: Sequence[HostIdentity]) -> tuple[HostIdentity, ...]:
    buckets = {site: list(values) for site, values in partition_by_site(hosts).items()}
    ordered: list[HostIdentity] = []
    while any(buckets.values()):
        for site in sorted(buckets):
            if buckets[site]:
                ordered.append(buckets[site].pop(0))
    return tuple(ordered)


def _chunks(values: Sequence[HostIdentity], size: int) -> tuple[tuple[HostIdentity, ...], ...]:
    if size <= 0:
        raise RolloutError("wave size must be positive")
    return tuple(tuple(values[index : index + size]) for index in range(0, len(values), size))


def choose_canaries(hosts: Sequence[HostIdentity], *, per_site: int = 1) -> tuple[HostIdentity, ...]:
    if per_site <= 0:
        raise RolloutError("per_site must be positive")
    canaries: list[HostIdentity] = []
    for site, candidates in partition_by_site(hosts).items():
        if not candidates:
            continue
        zone_seen: set[str] = set()
        for host in candidates:
            if len([candidate for candidate in canaries if candidate.site == site]) >= per_site:
                break
            if host.zone and host.zone in zone_seen:
                continue
            canaries.append(host)
            zone_seen.add(host.zone)
        needed = per_site - len([candidate for candidate in canaries if candidate.site == site])
        if needed > 0:
            already = {candidate.name for candidate in canaries}
            canaries.extend(host for host in candidates if host.name not in already)[:needed]
    return _ordered_hosts(canaries)


def create_rollout_plan(
    fleet: FleetModel,
    *,
    revision: str,
    roles: Sequence[str] = ("application",),
    sites: Sequence[str] | None = None,
    labels: Mapping[str, str] | None = None,
    canaries_per_site: int = 1,
    wave_size: int = 4,
    max_attempts: int = 2,
    failure_budget: int = 1,
) -> RolloutPlan:
    if not revision.strip():
        raise RolloutError("revision is required")
    selected = select_hosts(fleet, sites=sites, roles=roles, labels=labels)
    if not selected:
        raise RolloutError("rollout selector matched no hosts")
    canaries = choose_canaries(selected, per_site=canaries_per_site)
    canary_names = {host.name for host in canaries}
    remainder = tuple(host for host in _round_robin_site_hosts(selected) if host.name not in canary_names)
    waves: list[RolloutWave] = []
    waves.append(
        RolloutWave(
            index=0,
            hosts=tuple(host.name for host in canaries),
            canary=True,
            required_successes=len(canaries),
            max_failures=0,
        )
    )
    for offset, chunk in enumerate(_chunks(remainder, wave_size), start=1):
        allowed_failures = min(failure_budget, max(0, len(chunk) - 1))
        waves.append(
            RolloutWave(
                index=offset,
                hosts=tuple(host.name for host in chunk),
                canary=False,
                required_successes=len(chunk) - allowed_failures,
                max_failures=allowed_failures,
            )
        )
    return RolloutPlan(
        revision=revision,
        waves=tuple(waves),
        max_attempts=max_attempts,
        failure_budget=failure_budget,
        metadata={
            "selector_roles": ",".join(roles),
            "selector_sites": ",".join(sites or sorted(fleet.sites)),
        },
    )


def initial_state(plan: RolloutPlan) -> RolloutState:
    outcomes = {
        host: HostOutcome(host=host, target_revision=plan.revision)
        for host in plan.hosts()
    }
    return RolloutState(revision=plan.revision, outcomes=outcomes)


def validate_plan(plan: RolloutPlan) -> None:
    if not plan.waves:
        raise RolloutError("plan has no rollout waves")
    indices = tuple(wave.index for wave in plan.waves)
    if indices != tuple(range(len(plan.waves))):
        raise RolloutError(f"wave indices must be contiguous: {indices}")
    if not plan.waves[0].canary:
        raise RolloutError("first rollout wave must be canary")
    if any(wave.canary for wave in plan.waves[1:]):
        raise RolloutError("only first rollout wave may be canary")
    hosts = plan.hosts()
    if len(hosts) != len(set(hosts)):
        raise RolloutError("host appears in more than one wave")
    if plan.max_attempts < 1:
        raise RolloutError("max_attempts must be at least one")
    if plan.failure_budget < 0:
        raise RolloutError("failure_budget cannot be negative")


def wave_outcomes(plan: RolloutPlan, state: RolloutState, index: int) -> tuple[HostOutcome, ...]:
    wave = plan.wave(index)
    return tuple(state.outcome(host) for host in wave.hosts)


def wave_counts(plan: RolloutPlan, state: RolloutState, index: int) -> dict[str, int]:
    counts = {status.value: 0 for status in HostStatus}
    for outcome in wave_outcomes(plan, state, index):
        counts[outcome.status.value] += 1
    return counts


def evaluate_wave(plan: RolloutPlan, state: RolloutState, index: int) -> ProgressDecision:
    if state.halted:
        return ProgressDecision(False, True, state.halt_reason or "rollout already halted", None)
    wave = plan.wave(index)
    outcomes = wave_outcomes(plan, state, index)
    successful = [outcome for outcome in outcomes if outcome.at_target()]
    failed = [outcome for outcome in outcomes if outcome.status == HostStatus.FAILED]
    blocked = [outcome for outcome in outcomes if outcome.status == HostStatus.BLOCKED]
    active = [outcome for outcome in outcomes if outcome.status in {HostStatus.PENDING, HostStatus.IN_PROGRESS}]
    if active:
        return ProgressDecision(False, False, "wave still active", index)
    if wave.canary and (failed or blocked or len(successful) != len(outcomes)):
        return ProgressDecision(False, True, "canary wave did not reach target revision on every host", None)
    if len(failed) + len(blocked) > wave.max_failures:
        return ProgressDecision(False, True, "wave exceeded allowed failures", None)
    if len(successful) < wave.required_successes:
        return ProgressDecision(False, True, "wave did not meet required success count", None)
    if index + 1 >= len(plan.waves):
        return ProgressDecision(False, False, "rollout complete", None)
    return ProgressDecision(True, False, "wave satisfied progression gate", index + 1)


def mark_started(state: RolloutState, host: str) -> RolloutState:
    current = state.outcome(host)
    if state.halted:
        raise RolloutError("cannot start host after rollout halt")
    if current.at_target():
        return state
    if current.status == HostStatus.IN_PROGRESS:
        return state
    updated = replace(
        current,
        status=HostStatus.IN_PROGRESS,
        attempt=current.attempt + 1,
        message="",
    )
    outcomes = dict(state.outcomes)
    outcomes[host] = updated
    return replace(state, outcomes=outcomes)


def mark_succeeded(state: RolloutState, host: str, *, applied_revision: str) -> RolloutState:
    current = state.outcome(host)
    if current.status != HostStatus.IN_PROGRESS:
        raise RolloutError(f"host {host} is not in progress")
    if applied_revision != current.target_revision:
        raise RolloutError(
            f"host {host} reported revision {applied_revision}, expected {current.target_revision}"
        )
    updated = replace(
        current,
        status=HostStatus.SUCCEEDED,
        applied_revision=applied_revision,
        message="",
    )
    outcomes = dict(state.outcomes)
    outcomes[host] = updated
    return replace(state, outcomes=outcomes)


def mark_failed(state: RolloutState, host: str, *, message: str) -> RolloutState:
    current = state.outcome(host)
    if current.status != HostStatus.IN_PROGRESS:
        raise RolloutError(f"host {host} is not in progress")
    outcomes = dict(state.outcomes)
    outcomes[host] = replace(current, status=HostStatus.FAILED, message=message)
    return replace(state, outcomes=outcomes)


def mark_blocked(state: RolloutState, host: str, *, reason: str) -> RolloutState:
    current = state.outcome(host)
    if current.at_target():
        return state
    outcomes = dict(state.outcomes)
    outcomes[host] = replace(current, status=HostStatus.BLOCKED, message=reason)
    return replace(state, outcomes=outcomes)


def retry_candidates(plan: RolloutPlan, state: RolloutState, index: int) -> tuple[str, ...]:
    candidates: list[str] = []
    for outcome in wave_outcomes(plan, state, index):
        if outcome.at_target():
            continue
        if outcome.retryable(plan.max_attempts):
            candidates.append(outcome.host)
    return tuple(candidates)


def prepare_retry(plan: RolloutPlan, state: RolloutState, host: str) -> RolloutState:
    current = state.outcome(host)
    if current.at_target():
        return state
    if not current.retryable(plan.max_attempts):
        raise RolloutError(f"host {host} is not retryable")
    outcomes = dict(state.outcomes)
    outcomes[host] = replace(current, status=HostStatus.PENDING, message="")
    return replace(state, outcomes=outcomes)


def halt_rollout(state: RolloutState, reason: str) -> RolloutState:
    if not reason.strip():
        raise RolloutError("halt reason is required")
    return replace(state, halted=True, halt_reason=reason)


def advance_if_ready(plan: RolloutPlan, state: RolloutState) -> RolloutState:
    decision = evaluate_wave(plan, state, state.active_wave)
    if decision.halt:
        return halt_rollout(state, decision.reason)
    if decision.advance and decision.next_wave is not None:
        return replace(state, active_wave=decision.next_wave)
    return state


def reconcile_observed_revisions(
    plan: RolloutPlan,
    state: RolloutState,
    observed: Mapping[str, str],
) -> RolloutState:
    outcomes = dict(state.outcomes)
    for host, current in outcomes.items():
        observed_revision = str(observed.get(host, ""))
        if not observed_revision:
            continue
        if observed_revision == plan.revision:
            outcomes[host] = replace(
                current,
                status=HostStatus.SUCCEEDED,
                applied_revision=observed_revision,
                message="reconciled from observed state",
            )
        elif current.status == HostStatus.SUCCEEDED:
            outcomes[host] = replace(
                current,
                status=HostStatus.BLOCKED,
                applied_revision=observed_revision,
                message="observed revision diverged after successful apply",
            )
    return replace(state, outcomes=outcomes)


def eligible_hosts_for_active_wave(plan: RolloutPlan, state: RolloutState) -> tuple[str, ...]:
    wave = plan.wave(state.active_wave)
    return tuple(
        host
        for host in wave.hosts
        if not state.outcome(host).at_target()
        and state.outcome(host).status == HostStatus.PENDING
    )


def completed(plan: RolloutPlan, state: RolloutState) -> bool:
    if state.halted:
        return False
    return all(state.outcome(host).at_target() for host in plan.hosts())


def unfinished_hosts(plan: RolloutPlan, state: RolloutState) -> tuple[str, ...]:
    return tuple(host for host in plan.hosts() if not state.outcome(host).at_target())


def stable_plan_projection(plan: RolloutPlan) -> dict[str, Any]:
    return {
        "revision": plan.revision,
        "max_attempts": plan.max_attempts,
        "failure_budget": plan.failure_budget,
        "metadata": dict(sorted(plan.metadata.items())),
        "waves": [
            {
                "index": wave.index,
                "canary": wave.canary,
                "hosts": list(wave.hosts),
                "required_successes": wave.required_successes,
                "max_failures": wave.max_failures,
            }
            for wave in plan.waves
        ],
    }


def stable_state_projection(plan: RolloutPlan, state: RolloutState) -> dict[str, Any]:
    return {
        "revision": state.revision,
        "active_wave": state.active_wave,
        "halted": state.halted,
        "halt_reason": state.halt_reason,
        "complete": completed(plan, state),
        "outcomes": {
            host: {
                "status": outcome.status.value,
                "attempt": outcome.attempt,
                "target_revision": outcome.target_revision,
                "applied_revision": outcome.applied_revision,
                "message": outcome.message,
            }
            for host, outcome in sorted(state.outcomes.items())
        },
    }


def validate_state(plan: RolloutPlan, state: RolloutState) -> None:
    validate_plan(plan)
    if state.revision != plan.revision:
        raise RolloutError("state revision does not match rollout plan")
    if not 0 <= state.active_wave < len(plan.waves):
        raise RolloutError("active wave is outside plan bounds")
    if set(state.outcomes) != set(plan.hosts()):
        raise RolloutError("rollout state host set does not match plan")
    for host, outcome in state.outcomes.items():
        if outcome.host != host:
            raise RolloutError(f"outcome key mismatch for {host}")
        if outcome.target_revision != plan.revision:
            raise RolloutError(f"host {host} has wrong target revision")
        if outcome.attempt < 0 or outcome.attempt > plan.max_attempts:
            raise RolloutError(f"host {host} has invalid attempt count")
        if outcome.status == HostStatus.SUCCEEDED and outcome.applied_revision != plan.revision:
            raise RolloutError(f"host {host} marked succeeded at wrong revision")


def summarize_wave(plan: RolloutPlan, state: RolloutState, index: int) -> dict[str, Any]:
    wave = plan.wave(index)
    decision = evaluate_wave(plan, state, index)
    return {
        "wave": index,
        "canary": wave.canary,
        "hosts": list(wave.hosts),
        "counts": wave_counts(plan, state, index),
        "required_successes": wave.required_successes,
        "max_failures": wave.max_failures,
        "decision": {
            "advance": decision.advance,
            "halt": decision.halt,
            "reason": decision.reason,
            "next_wave": decision.next_wave,
        },
    }


def rollout_report(plan: RolloutPlan, state: RolloutState) -> dict[str, Any]:
    validate_state(plan, state)
    return {
        "plan": stable_plan_projection(plan),
        "state": stable_state_projection(plan, state),
        "waves": [summarize_wave(plan, state, wave.index) for wave in plan.waves],
        "unfinished_hosts": list(unfinished_hosts(plan, state)),
    }
