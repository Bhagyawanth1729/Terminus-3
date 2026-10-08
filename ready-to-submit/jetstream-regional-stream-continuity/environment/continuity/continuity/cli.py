from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .engine import ContinuityEngine
from .model import (
    ContractError,
    FencingError,
    GenerationConflict,
    ReplayConflict,
    to_iso,
    utcnow,
)
from .policy import OriginObservation
from .runtime import (
    ArchiveSynchronizer,
    ConsumerRunner,
    JetStreamAdmin,
    LabProcessManager,
    NatsConnectionPool,
    NatsPublisher,
    RuntimeBootstrap,
    endpoints_from_engine,
)
from .store import ContinuityStore


DEFAULT_ROOT = Path("/app/continuity")


class CliFailure(RuntimeError):
    pass


def dump(document: Any, *, pretty: bool = True) -> None:
    if pretty:
        print(json.dumps(document, indent=2, sort_keys=True, default=str))
    else:
        print(json.dumps(document, sort_keys=True, separators=(",", ":"), default=str))


def root_from_args(args: argparse.Namespace) -> Path:
    value = getattr(args, "root", None)
    return Path(value) if value else DEFAULT_ROOT


def db_path(root: Path) -> Path:
    return root / "state" / "continuity.db"


def config_path(root: Path) -> Path:
    return root / "config" / "continuity.json"


def make_engine(root: Path) -> ContinuityEngine:
    store = ContinuityStore(db_path(root))
    return ContinuityEngine.from_json_file(store, config_path(root))


def ensure_database(root: Path, *, reset: bool = False) -> Path:
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    database = db_path(root)
    if reset and database.exists():
        database.unlink()
    if database.exists():
        _apply_runtime_extensions(root, database)
        return database
    schema = root / "sql" / "schema.sql"
    seed = root / "sql" / "seed.sql"
    if not schema.exists() or not seed.exists():
        raise CliFailure("schema.sql and seed.sql are required to initialize continuity state")
    connection = sqlite3.connect(database)
    try:
        connection.executescript(schema.read_text(encoding="utf-8"))
        connection.executescript(seed.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()
    _apply_runtime_extensions(root, database)
    return database


def _apply_runtime_extensions(root: Path, database: Path) -> None:
    extension = root / "sql" / "runtime_extensions.sql"
    if not extension.exists():
        return
    connection = sqlite3.connect(database)
    try:
        connection.executescript(extension.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()


def command_db_init(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    database = ensure_database(root, reset=bool(args.reset))
    dump({"database": str(database), "reset": bool(args.reset)})
    return 0


def command_status(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    report = engine.inspect_health()
    document = report.as_dict()
    if args.write:
        engine.write_report(root / "out" / "health.json", document)
    dump(document, pretty=not args.compact)
    return 0 if report.healthy else 2


def command_reconcile(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    if args.region:
        generation = engine.store.confirmed_generation(args.region)
        if generation is None:
            raise CliFailure(f"region {args.region} has no confirmed origin generation")
        summary = engine.reconcile_region(args.region, generation.generation)
        document = {args.region: summary.as_dict()}
        converged = summary.converged
    else:
        summaries = engine.reconcile_all()
        document = {region: summary.as_dict() for region, summary in summaries.items()}
        converged = all(summary.converged for summary in summaries.values())
    output = {
        "generated_at": to_iso(utcnow()),
        "converged": converged,
        "regions": document,
    }
    if args.write:
        engine.write_report(root / "out" / "reconciliation.json", output)
    dump(output, pretty=not args.compact)
    return 0 if converged else 2


def command_generations(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    values = engine.store.list_generations(args.region)
    dump([item.as_dict() for item in values], pretty=not args.compact)
    return 0


def command_observe_origin(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    observation = OriginObservation(
        region=args.region,
        stream_name=args.stream,
        domain=args.domain,
        stream_fingerprint=args.fingerprint,
        first_sequence=int(args.first),
        last_sequence=int(args.last),
        observed_at=utcnow(),
    )
    record = engine.validate_origin_observation(observation)
    dump(record.as_dict(), pretty=not args.compact)
    return 0 if record.status.value == "CONFIRMED" else 2


async def async_publish(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    event = engine.store.event_by_id(args.event_id)
    if event is None:
        raise CliFailure(f"event {args.event_id} is not in the edge journal")
    pool = NatsConnectionPool()
    try:
        publisher = NatsPublisher(pool, endpoints_from_engine(engine)[event.identity.region])
        ack = await engine.publish_event(args.event_id, publisher)
        dump(ack.as_dict(), pretty=not args.compact)
        return 0
    finally:
        await pool.close()


def command_approve_generation(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    value = engine.store.approve_generation(
        args.region,
        int(args.generation),
        approved_by=args.approved_by,
    )
    dump(value.as_dict())
    return 0


def command_plan_replay(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    generation = int(args.generation) if args.generation else None
    if generation is None:
        current = engine.store.confirmed_generation(args.region)
        if current is None:
            raise CliFailure(f"region {args.region} has no confirmed generation")
        generation = current.generation
    decision = engine.plan_replay(
        region=args.region,
        generation=generation,
        created_by=args.created_by,
        reason=args.reason,
        approve=bool(args.approve),
        approved_by=args.approved_by if args.approve else None,
    )
    document = {
        "blocked_reason": decision.blocked_reason,
        "missing_event_ids": list(decision.missing_event_ids),
        "plan": None if decision.plan is None else decision.plan.as_dict(),
    }
    dump(document, pretty=not args.compact)
    return 2 if decision.blocked_reason else 0


def command_list_replay(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    plans = engine.store.active_replay_plans(region=args.region)
    dump([plan.as_dict() for plan in plans], pretty=not args.compact)
    return 0


def command_lease(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    if args.lease_action == "show":
        lease = engine.store.current_lease(args.region)
        dump(None if lease is None else lease.as_dict())
        return 0
    if args.lease_action == "acquire":
        lease = engine.acquire_recovery_lease(
            region=args.region,
            owner_id=args.owner,
            ttl_seconds=int(args.ttl),
        )
        dump(lease.as_dict())
        return 0
    if args.lease_action == "renew":
        lease = engine.renew_recovery_lease(
            region=args.region,
            owner_id=args.owner,
            fence_epoch=int(args.epoch),
            ttl_seconds=int(args.ttl),
        )
        dump(lease.as_dict())
        return 0
    if args.lease_action == "release":
        engine.store.release_lease(
            args.region,
            owner_id=args.owner,
            fence_epoch=int(args.epoch),
        )
        dump({"released": True, "region": args.region, "owner": args.owner, "epoch": int(args.epoch)})
        return 0
    raise CliFailure(f"unsupported lease action {args.lease_action}")


def command_retention(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    generation = int(args.generation) if args.generation else None
    if generation is None:
        current = engine.store.confirmed_generation(args.region)
        if current is None:
            raise CliFailure(f"region {args.region} has no confirmed generation")
        generation = current.generation
    decision = engine.compute_retention_decision(
        region=args.region,
        generation=generation,
        limit=int(args.limit),
    )
    document = {
        "region": decision.region,
        "generation": decision.generation,
        "safe_sequence": decision.safe_sequence,
        "archive_sequence": decision.archive_sequence,
        "required_consumer_sequence": decision.required_consumer_sequence,
        "replay_pin_sequence": decision.replay_pin_sequence,
        "horizon_safe": decision.horizon_safe,
        "eligible_count": len(decision.eligible_event_ids),
        "eligible_event_ids": list(decision.eligible_event_ids),
    }
    if args.apply:
        document["deleted"] = engine.apply_retention(decision)
    dump(document, pretty=not args.compact)
    return 0 if decision.horizon_safe else 2


async def async_lab_start(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    manager = LabProcessManager(root)
    pids = manager.start_all()
    ready = manager.wait_all(timeout=float(args.timeout))
    engine = make_engine(root)
    pool = NatsConnectionPool()
    try:
        admin = JetStreamAdmin(pool, endpoints_from_engine(engine))
        bootstrap = RuntimeBootstrap(engine, admin)
        streams = await bootstrap.ensure_all()
        result = {
            "pids": pids,
            "ready": {name: {"server_id": value.get("server_id"), "version": value.get("version")} for name, value in ready.items()},
            "streams": {
                "east": streams["east"].__dict__,
                "west": streams["west"].__dict__,
                "hub": streams["hub"].__dict__,
            },
            "consumers": [value.__dict__ for value in streams["consumers"]],
        }
        dump(result, pretty=not args.compact)
    finally:
        await pool.close()
    return 0


def command_lab_stop(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    manager = LabProcessManager(root)
    before = manager.status()
    manager.stop_all()
    after = manager.status()
    dump({"before": before, "after": after})
    return 0


def command_lab_status(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    manager = LabProcessManager(root)
    dump(manager.status())
    return 0


async def async_archive_sync(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    pool = NatsConnectionPool()
    try:
        admin = JetStreamAdmin(pool, endpoints_from_engine(engine))
        synchronizer = ArchiveSynchronizer(engine=engine, admin=admin)
        inserted = await synchronizer.sync(
            start_sequence=args.start_sequence,
            maximum_messages=args.maximum_messages,
        )
        dump({"inserted": inserted, "archive_count": engine.store.archive_count()})
    finally:
        await pool.close()
    return 0


async def async_execute_replay(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    plan = engine.store.replay_plan(args.plan_id)
    if plan is None:
        raise CliFailure(f"unknown replay plan {args.plan_id}")
    lease = engine.store.current_lease(plan.replay_range.region)
    if lease is None:
        raise CliFailure(f"region {plan.replay_range.region} has no recovery lease")
    owner = args.owner or lease.owner_id
    epoch = int(args.epoch) if args.epoch is not None else lease.fence_epoch
    pool = NatsConnectionPool()
    try:
        endpoint = endpoints_from_engine(engine)[plan.replay_range.region]
        publisher = NatsPublisher(pool, endpoint)
        outcome = await engine.execute_replay_plan(
            args.plan_id,
            owner_id=owner,
            fence_epoch=epoch,
            publisher=publisher,
        )
        dump(outcome.__dict__)
        return 0 if outcome.completed else 2
    finally:
        await pool.close()


async def async_run_consumer(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    pool = NatsConnectionPool()
    try:
        hub = endpoints_from_engine(engine)["hub"]
        stream_name = engine.topology().hub_archive.name
        runner = ConsumerRunner(pool=pool, endpoint=hub, engine=engine, stream_name=stream_name)
        counters = await runner.process_until_idle(
            args.consumer,
            worker_id=args.worker,
            fence_epoch=int(args.epoch),
            maximum_messages=int(args.max_messages),
            batch=int(args.batch),
        )
        dump(counters)
        return 0 if counters["failed"] == 0 else 2
    finally:
        await pool.close()


def command_reset(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    manager = LabProcessManager(root)
    manager.stop_all()
    state = root / "state"
    nats_state = state / "nats"
    if nats_state.exists():
        shutil.rmtree(nats_state)
    database = db_path(root)
    if database.exists():
        database.unlink()
    ensure_database(root)
    out = root / "out"
    if out.exists():
        for path in out.iterdir():
            if path.is_file():
                path.unlink()
    dump({"reset": True, "database": str(database), "nats_state": str(nats_state)})
    return 0


def command_verify(args: argparse.Namespace) -> int:
    root = root_from_args(args)
    ensure_database(root)
    engine = make_engine(root)
    health = engine.inspect_health()
    reconciliation = engine.write_reconciliation_report(root / "out" / "reconciliation.json")
    engine.write_report(root / "out" / "health.json", health.as_dict())
    document = {
        "healthy": health.healthy,
        "converged": reconciliation["converged"],
        "health": health.as_dict(),
        "reconciliation": reconciliation,
    }
    dump(document, pretty=not args.compact)
    return 0 if health.healthy and reconciliation["converged"] else 2


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="continuity runtime root")
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="continuityctl",
        description="Regional JetStream continuity operator control plane",
    )
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help=argparse.SUPPRESS)
    parser.add_argument("--compact", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    db = sub.add_parser("db-init", help="initialize or reset durable SQLite state")
    add_common(db)
    db.add_argument("--reset", action="store_true")
    db.set_defaults(func=command_db_init)

    status = sub.add_parser("inspect", help="inspect continuity health")
    add_common(status)
    status.add_argument("--write", action="store_true", default=True)
    status.set_defaults(func=command_status)

    reconcile = sub.add_parser("reconcile", help="compare journal, archive and required consumers")
    add_common(reconcile)
    reconcile.add_argument("--region", choices=("east", "west"))
    reconcile.add_argument("--write", action="store_true", default=True)
    reconcile.set_defaults(func=command_reconcile)

    generations = sub.add_parser("generations", help="show origin generations")
    add_common(generations)
    generations.add_argument("--region", choices=("east", "west"))
    generations.set_defaults(func=command_generations)

    approve = sub.add_parser("approve-generation", help="approve a pending origin generation")
    add_common(approve)
    approve.add_argument("region", choices=("east", "west"))
    approve.add_argument("generation", type=int)
    approve.add_argument("--approved-by", required=True)
    approve.set_defaults(func=command_approve_generation)

    observe = sub.add_parser("observe-origin", help="record an origin stream observation")
    add_common(observe)
    observe.add_argument("region", choices=("east", "west"))
    observe.add_argument("--stream", required=True)
    observe.add_argument("--domain", required=True)
    observe.add_argument("--fingerprint", required=True)
    observe.add_argument("--first", required=True, type=int)
    observe.add_argument("--last", required=True, type=int)
    observe.set_defaults(func=command_observe_origin)

    publish = sub.add_parser("publish", help="publish one accepted journal event to its origin stream")
    add_common(publish)
    publish.add_argument("event_id")
    publish.set_defaults(async_func=async_publish)

    replay = sub.add_parser("plan-replay", help="build a replay plan from reconciliation gaps")
    add_common(replay)
    replay.add_argument("region", choices=("east", "west"))
    replay.add_argument("--generation", type=int)
    replay.add_argument("--created-by", required=True)
    replay.add_argument("--reason", required=True)
    replay.add_argument("--approve", action="store_true")
    replay.add_argument("--approved-by")
    replay.set_defaults(func=command_plan_replay)

    list_replay = sub.add_parser("list-replay", help="show active replay plans")
    add_common(list_replay)
    list_replay.add_argument("--region", choices=("east", "west"))
    list_replay.set_defaults(func=command_list_replay)

    execute = sub.add_parser("execute-replay", help="execute an approved replay plan")
    add_common(execute)
    execute.add_argument("plan_id")
    execute.add_argument("--owner")
    execute.add_argument("--epoch", type=int)
    execute.set_defaults(async_func=async_execute_replay)

    lease = sub.add_parser("lease", help="manage fenced recovery ownership")
    add_common(lease)
    lease_sub = lease.add_subparsers(dest="lease_action", required=True)
    for name in ("show", "acquire", "renew", "release"):
        item = lease_sub.add_parser(name)
        item.add_argument("region", choices=("east", "west"))
        if name != "show":
            item.add_argument("--owner", required=True)
        if name in {"renew", "release"}:
            item.add_argument("--epoch", required=True, type=int)
        if name in {"acquire", "renew"}:
            item.add_argument("--ttl", default=30, type=int)
    lease.set_defaults(func=command_lease)

    retention = sub.add_parser("retention", help="preview or apply journal cleanup")
    add_common(retention)
    retention.add_argument("region", choices=("east", "west"))
    retention.add_argument("--generation", type=int)
    retention.add_argument("--limit", default=1000, type=int)
    retention.add_argument("--apply", action="store_true")
    retention.set_defaults(func=command_retention)

    lab_start = sub.add_parser("lab-start", help="start the three NATS domains and configure streams")
    add_common(lab_start)
    lab_start.add_argument("--timeout", default=10.0, type=float)
    lab_start.set_defaults(async_func=async_lab_start)

    lab_stop = sub.add_parser("lab-stop", help="stop local NATS domains")
    add_common(lab_stop)
    lab_stop.set_defaults(func=command_lab_stop)

    lab_status = sub.add_parser("lab-status", help="show local NATS process state")
    add_common(lab_status)
    lab_status.set_defaults(func=command_lab_status)

    archive_sync = sub.add_parser("archive-sync", help="materialize current hub archive into durable index")
    add_common(archive_sync)
    archive_sync.add_argument("--start-sequence", type=int)
    archive_sync.add_argument("--maximum-messages", type=int)
    archive_sync.set_defaults(async_func=async_archive_sync)

    consumer = sub.add_parser("run-consumer", help="drain one durable consumer")
    add_common(consumer)
    consumer.add_argument("consumer")
    consumer.add_argument("--worker", required=True)
    consumer.add_argument("--epoch", type=int, default=0)
    consumer.add_argument("--max-messages", type=int, default=5000)
    consumer.add_argument("--batch", type=int, default=100)
    consumer.set_defaults(async_func=async_run_consumer)

    reset = sub.add_parser("reset", help="restore inherited database and empty NATS runtime state")
    add_common(reset)
    reset.set_defaults(func=command_reset)

    verify = sub.add_parser("verify", help="write final health and reconciliation reports")
    add_common(verify)
    verify.set_defaults(func=command_verify)

    return parser


async def async_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if hasattr(args, "async_func"):
            return int(await args.async_func(args))
        if hasattr(args, "func"):
            return int(args.func(args))
        parser.error("command has no handler")
    except (
        CliFailure,
        ContractError,
        FencingError,
        GenerationConflict,
        ReplayConflict,
        OSError,
        sqlite3.Error,
    ) as exc:
        print(f"continuityctl: {exc}", file=sys.stderr)
        return 2
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if hasattr(args, "async_func"):
            return int(asyncio.run(_run_async(args)))
        if hasattr(args, "func"):
            return int(args.func(args))
        parser.error("command has no handler")
    except (
        CliFailure,
        ContractError,
        FencingError,
        GenerationConflict,
        ReplayConflict,
        OSError,
        sqlite3.Error,
    ) as exc:
        print(f"continuityctl: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 2


async def _run_async(args: argparse.Namespace) -> int:
    try:
        return int(await args.async_func(args))
    except (
        CliFailure,
        ContractError,
        FencingError,
        GenerationConflict,
        ReplayConflict,
        OSError,
        sqlite3.Error,
    ) as exc:
        print(f"continuityctl: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
