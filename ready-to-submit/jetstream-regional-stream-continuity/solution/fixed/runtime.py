from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import nats
from nats.aio.client import Client as NATS
from nats.aio.msg import Msg

from .model import (
    ArchiveRecord,
    ContractError,
    EventEnvelope,
    EventIdentity,
    PublishAck,
    StreamPolicy,
    Topology,
    canonical_json,
    parse_iso,
    to_iso,
    utcnow,
)
from .policy import ContinuityEngine, Delivery, Publisher
from .store import ContinuityStore


@dataclass(frozen=True)
class NatsEndpoint:
    name: str
    url: str
    domain: str
    monitor_url: str


@dataclass(frozen=True)
class StreamSnapshot:
    name: str
    domain: str
    messages: int
    bytes: int
    first_sequence: int
    last_sequence: int
    consumer_count: int
    config: Mapping[str, Any]
    cluster: Mapping[str, Any] | None
    sources: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ConsumerSnapshot:
    stream_name: str
    consumer_name: str
    delivered_stream_sequence: int
    ack_floor_stream_sequence: int
    num_ack_pending: int
    num_pending: int
    num_redelivered: int
    config: Mapping[str, Any]


@dataclass(frozen=True)
class RawMessage:
    stream_name: str
    sequence: int
    subject: str
    time: datetime
    data: bytes
    headers: Mapping[str, str]


class JsonApiError(RuntimeError):
    def __init__(self, subject: str, error: Mapping[str, Any]) -> None:
        self.subject = subject
        self.error = dict(error)
        super().__init__(f"JetStream API error on {subject}: {canonical_json(self.error)}")


class NatsConnectionPool:
    def __init__(self) -> None:
        self._clients: dict[str, NATS] = {}
        self._lock = asyncio.Lock()

    async def get(self, endpoint: NatsEndpoint) -> NATS:
        async with self._lock:
            client = self._clients.get(endpoint.url)
            if client is not None and client.is_connected:
                return client
            client = await nats.connect(
                servers=[endpoint.url],
                name=f"continuity-{endpoint.name}",
                connect_timeout=2,
                reconnect_time_wait=0.5,
                max_reconnect_attempts=5,
                allow_reconnect=True,
            )
            self._clients[endpoint.url] = client
            return client

    async def close(self) -> None:
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                await client.drain()
            except Exception:
                try:
                    await client.close()
                except Exception:
                    pass


class JetStreamAdmin:
    def __init__(self, pool: NatsConnectionPool, endpoints: Mapping[str, NatsEndpoint]) -> None:
        self.pool = pool
        self.endpoints = dict(endpoints)

    def endpoint(self, name: str) -> NatsEndpoint:
        try:
            return self.endpoints[name]
        except KeyError as exc:
            raise ContractError(f"unknown NATS endpoint {name!r}") from exc

    def api_prefix(self, endpoint: NatsEndpoint) -> str:
        return f"$JS.{endpoint.domain}.API" if endpoint.domain else "$JS.API"

    async def request_api(
        self,
        endpoint_name: str,
        suffix: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float = 3.0,
    ) -> Mapping[str, Any]:
        endpoint = self.endpoint(endpoint_name)
        client = await self.pool.get(endpoint)
        subject = f"{self.api_prefix(endpoint)}.{suffix}"
        response = await client.request(
            subject,
            canonical_json(dict(payload or {})).encode("utf-8"),
            timeout=timeout,
        )
        document = json.loads(response.data.decode("utf-8"))
        if not isinstance(document, Mapping):
            raise ContractError(f"JetStream API returned non-object response for {subject}")
        if "error" in document:
            error = document["error"]
            if isinstance(error, Mapping):
                raise JsonApiError(subject, error)
            raise JsonApiError(subject, {"description": str(error)})
        return document

    async def stream_info(self, endpoint_name: str, stream_name: str) -> StreamSnapshot:
        document = await self.request_api(endpoint_name, f"STREAM.INFO.{stream_name}")
        config = document.get("config") or {}
        state = document.get("state") or {}
        if not isinstance(config, Mapping) or not isinstance(state, Mapping):
            raise ContractError(f"malformed stream info for {stream_name}")
        cluster = document.get("cluster")
        sources = document.get("sources") or ()
        source_values: list[Mapping[str, Any]] = []
        if isinstance(sources, Sequence):
            source_values.extend(value for value in sources if isinstance(value, Mapping))
        endpoint = self.endpoint(endpoint_name)
        return StreamSnapshot(
            name=str(config.get("name", stream_name)),
            domain=endpoint.domain,
            messages=int(state.get("messages", 0)),
            bytes=int(state.get("bytes", 0)),
            first_sequence=int(state.get("first_seq", 0)),
            last_sequence=int(state.get("last_seq", 0)),
            consumer_count=int(state.get("consumer_count", 0)),
            config=dict(config),
            cluster=dict(cluster) if isinstance(cluster, Mapping) else None,
            sources=tuple(source_values),
        )

    async def stream_exists(self, endpoint_name: str, stream_name: str) -> bool:
        try:
            await self.stream_info(endpoint_name, stream_name)
        except JsonApiError as exc:
            code = int(exc.error.get("err_code", 0) or 0)
            description = str(exc.error.get("description", "")).lower()
            if code in {10059, 10039} or "stream not found" in description:
                return False
            raise
        return True

    async def upsert_stream(
        self,
        endpoint_name: str,
        stream_name: str,
        config: Mapping[str, Any],
    ) -> StreamSnapshot:
        exists = await self.stream_exists(endpoint_name, stream_name)
        suffix = f"STREAM.UPDATE.{stream_name}" if exists else f"STREAM.CREATE.{stream_name}"
        payload = dict(config)
        payload["name"] = stream_name
        await self.request_api(endpoint_name, suffix, payload)
        return await self.stream_info(endpoint_name, stream_name)

    async def consumer_info(
        self,
        endpoint_name: str,
        stream_name: str,
        consumer_name: str,
    ) -> ConsumerSnapshot:
        document = await self.request_api(
            endpoint_name,
            f"CONSUMER.INFO.{stream_name}.{consumer_name}",
        )
        config = document.get("config") or {}
        delivered = document.get("delivered") or {}
        ack_floor = document.get("ack_floor") or {}
        return ConsumerSnapshot(
            stream_name=stream_name,
            consumer_name=consumer_name,
            delivered_stream_sequence=int(delivered.get("stream_seq", 0)) if isinstance(delivered, Mapping) else 0,
            ack_floor_stream_sequence=int(ack_floor.get("stream_seq", 0)) if isinstance(ack_floor, Mapping) else 0,
            num_ack_pending=int(document.get("num_ack_pending", 0)),
            num_pending=int(document.get("num_pending", 0)),
            num_redelivered=int(document.get("num_redelivered", 0)),
            config=dict(config) if isinstance(config, Mapping) else {},
        )

    async def upsert_consumer(
        self,
        endpoint_name: str,
        stream_name: str,
        consumer_name: str,
        *,
        filter_subject: str,
        ack_wait_seconds: int,
        max_ack_pending: int,
    ) -> ConsumerSnapshot:
        payload = {
            "stream_name": stream_name,
            "config": {
                "name": consumer_name,
                "durable_name": consumer_name,
                "ack_policy": "explicit",
                "deliver_policy": "all",
                "replay_policy": "instant",
                "filter_subject": filter_subject,
                "ack_wait": ack_wait_seconds * 1_000_000_000,
                "max_ack_pending": max_ack_pending,
            },
        }
        try:
            await self.request_api(
                endpoint_name,
                f"CONSUMER.DURABLE.CREATE.{stream_name}.{consumer_name}",
                payload,
            )
        except JsonApiError as exc:
            description = str(exc.error.get("description", "")).lower()
            if "consumer name already in use" not in description and "consumer already exists" not in description:
                raise
            await self.request_api(
                endpoint_name,
                f"CONSUMER.CREATE.{stream_name}.{consumer_name}",
                payload,
            )
        return await self.consumer_info(endpoint_name, stream_name, consumer_name)

    async def get_message_by_sequence(
        self,
        endpoint_name: str,
        stream_name: str,
        sequence: int,
    ) -> RawMessage:
        document = await self.request_api(
            endpoint_name,
            f"STREAM.MSG.GET.{stream_name}",
            {"seq": sequence},
        )
        message = document.get("message")
        if not isinstance(message, Mapping):
            raise ContractError(f"stream {stream_name} seq {sequence} response has no message")
        data = base64.b64decode(str(message.get("data", ""))) if message.get("data") else b""
        headers = self._decode_headers(message.get("hdrs"))
        timestamp = parse_iso(str(message.get("time", ""))) or utcnow()
        return RawMessage(
            stream_name=stream_name,
            sequence=int(message.get("seq", sequence)),
            subject=str(message.get("subject", "")),
            time=timestamp,
            data=data,
            headers=headers,
        )

    def _decode_headers(self, encoded: Any) -> Mapping[str, str]:
        if not encoded:
            return {}
        raw = base64.b64decode(str(encoded)).decode("utf-8", errors="replace")
        result: dict[str, str] = {}
        for line in raw.replace("\r\n", "\n").split("\n"):
            if not line or line.startswith("NATS/") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
        return result

    async def monitor(self, endpoint_name: str, path: str = "/varz") -> Mapping[str, Any]:
        endpoint = self.endpoint(endpoint_name)
        url = endpoint.monitor_url.rstrip("/") + "/" + path.lstrip("/")

        def fetch() -> Mapping[str, Any]:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                document = json.loads(response.read().decode("utf-8"))
            if not isinstance(document, Mapping):
                raise ContractError(f"monitor endpoint returned non-object for {url}")
            return document

        return await asyncio.to_thread(fetch)


class NatsPublisher(Publisher):
    def __init__(
        self,
        pool: NatsConnectionPool,
        endpoint: NatsEndpoint,
        *,
        timeout_seconds: float = 3.0,
    ) -> None:
        self.pool = pool
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    async def publish(self, event: EventEnvelope, *, message_id: str, expected_stream: str) -> PublishAck:
        client = await self.pool.get(self.endpoint)
        headers = event.headers()
        headers["Nats-Msg-Id"] = message_id
        headers["Nats-Expected-Stream"] = expected_stream
        response = await client.request(
            event.raw_subject,
            event.wire_payload(),
            headers=headers,
            timeout=self.timeout_seconds,
        )
        document = json.loads(response.data.decode("utf-8"))
        if not isinstance(document, Mapping):
            raise ContractError("JetStream publish acknowledgement is not a JSON object")
        if "error" in document:
            error = document["error"]
            if isinstance(error, Mapping):
                raise JsonApiError(event.raw_subject, error)
            raise JsonApiError(event.raw_subject, {"description": str(error)})
        stream = str(document.get("stream", ""))
        sequence = int(document.get("seq", 0))
        duplicate = bool(document.get("duplicate", False))
        if stream != expected_stream:
            raise ContractError(
                f"publish acknowledgement came from {stream!r}, expected {expected_stream!r}"
            )
        return PublishAck(
            event_id=event.identity.event_id,
            stream=stream,
            sequence=sequence,
            duplicate=duplicate,
            acknowledged_at=utcnow(),
        )


class PullDelivery(Delivery):
    def __init__(
        self,
        *,
        msg: Msg,
        event: EventEnvelope,
        consumer_name: str,
        delivery_count: int,
        jetstream_ack_floor: int,
    ) -> None:
        self.msg = msg
        self.event = event
        self.consumer_name = consumer_name
        self.delivery_count = delivery_count
        self.jetstream_ack_floor = jetstream_ack_floor

    async def ack(self) -> None:
        await self.msg.ack()

    async def nak(self, delay_seconds: int | None = None) -> None:
        if delay_seconds is None:
            await self.msg.nak()
        else:
            await self.msg.nak(delay=delay_seconds)


class ConsumerRunner:
    def __init__(
        self,
        *,
        pool: NatsConnectionPool,
        endpoint: NatsEndpoint,
        engine: ContinuityEngine,
        stream_name: str,
    ) -> None:
        self.pool = pool
        self.endpoint = endpoint
        self.engine = engine
        self.stream_name = stream_name

    async def pull_batch(
        self,
        consumer_name: str,
        *,
        batch: int = 50,
        timeout: float = 1.0,
    ) -> list[PullDelivery]:
        client = await self.pool.get(self.endpoint)
        js = client.jetstream(domain=self.endpoint.domain)
        subscription = await js.pull_subscribe(
            subject="telemetry.raw.>",
            durable=consumer_name,
            stream=self.stream_name,
        )
        try:
            messages = await subscription.fetch(batch=batch, timeout=timeout)
        except TimeoutError:
            return []
        result: list[PullDelivery] = []
        for msg in messages:
            document = json.loads(msg.data.decode("utf-8"))
            if not isinstance(document, Mapping):
                await msg.term()
                continue
            event = EventEnvelope.from_mapping(document)
            metadata = msg.metadata
            delivery_count = 1
            ack_floor = 0
            if metadata is not None:
                delivery_count = int(metadata.num_delivered)
                ack_floor = int(metadata.sequence.stream)
            result.append(
                PullDelivery(
                    msg=msg,
                    event=event,
                    consumer_name=consumer_name,
                    delivery_count=delivery_count,
                    jetstream_ack_floor=ack_floor,
                )
            )
        return result

    async def process_until_idle(
        self,
        consumer_name: str,
        *,
        worker_id: str,
        fence_epoch: int,
        maximum_messages: int = 5000,
        batch: int = 100,
    ) -> dict[str, int]:
        counters = {"processed": 0, "duplicates": 0, "quarantined": 0, "failed": 0}
        while counters["processed"] + counters["failed"] < maximum_messages:
            deliveries = await self.pull_batch(consumer_name, batch=batch)
            if not deliveries:
                break
            for delivery in deliveries:
                try:
                    result = await self.engine.process_delivery(
                        delivery,
                        worker_id=worker_id,
                        fence_epoch=fence_epoch,
                    )
                except Exception:
                    counters["failed"] += 1
                    try:
                        await delivery.nak(delay_seconds=1)
                    except Exception:
                        pass
                    continue
                counters["processed"] += 1
                if result.duplicate_effect:
                    counters["duplicates"] += 1
                if result.status == "QUARANTINED":
                    counters["quarantined"] += 1
        return counters


class RuntimeBootstrap:
    def __init__(self, engine: ContinuityEngine, admin: JetStreamAdmin) -> None:
        self.engine = engine
        self.admin = admin

    def _stream_config(self, policy: StreamPolicy, subjects: Sequence[str]) -> dict[str, Any]:
        return {
            "subjects": list(subjects),
            "retention": policy.retention,
            "storage": policy.storage,
            "num_replicas": policy.replicas,
            "duplicate_window": policy.duplicate_window_seconds * 1_000_000_000,
            "max_age": policy.max_age_seconds * 1_000_000_000,
            "allow_direct": policy.allow_direct,
            "deny_delete": policy.deny_delete,
            "deny_purge": policy.deny_purge,
        }

    async def ensure_origin(self, region: str) -> StreamSnapshot:
        cfg = self.engine.region_config(region)
        policy = self.engine.edge_stream_policy(region)
        stream_name = str(cfg["stream_name"])
        subjects = [str(cfg["subject_prefix"]) + ".>"]
        stream_cfg = self._stream_config(policy, subjects)
        return await self.admin.upsert_stream(region, stream_name, stream_cfg)

    async def ensure_hub_archive(self) -> StreamSnapshot:
        topology = self.engine.topology()
        policy = self.engine.hub_stream_policy()
        config = self._stream_config(policy, topology.hub_archive.subjects)
        config["sources"] = [
            {
                "name": source.origin.name,
                "external": {
                    "api": f"$JS.{source.origin.domain}.API",
                    "deliver": f"_CONTINUITY.SOURCE.{source.region}",
                },
                "subject_transforms": [
                    {
                        "src": source.origin.subjects[0] if source.origin.subjects else f"telemetry.{source.region}.>",
                        "dest": source.destination_prefix + ".>",
                    }
                ],
            }
            for source in topology.sources
        ]
        return await self.admin.upsert_stream("hub", topology.hub_archive.name, config)

    async def ensure_consumers(self) -> list[ConsumerSnapshot]:
        topology = self.engine.topology()
        result: list[ConsumerSnapshot] = []
        for consumer in self.engine.store.consumers():
            if not bool(consumer["enabled"]):
                continue
            result.append(
                await self.admin.upsert_consumer(
                    "hub",
                    topology.hub_archive.name,
                    str(consumer["consumer_name"]),
                    filter_subject=str(consumer["filter_subject"]),
                    ack_wait_seconds=int(consumer["ack_wait_seconds"]),
                    max_ack_pending=int(consumer["max_ack_pending"]),
                )
            )
        return result

    async def ensure_all(self) -> dict[str, Any]:
        east = await self.ensure_origin("east")
        west = await self.ensure_origin("west")
        hub = await self.ensure_hub_archive()
        consumers = await self.ensure_consumers()
        return {
            "east": east,
            "west": west,
            "hub": hub,
            "consumers": consumers,
        }


class ArchiveSynchronizer:
    def __init__(
        self,
        *,
        engine: ContinuityEngine,
        admin: JetStreamAdmin,
        hub_endpoint_name: str = "hub",
    ) -> None:
        self.engine = engine
        self.admin = admin
        self.hub_endpoint_name = hub_endpoint_name

    async def sync(self, *, start_sequence: int | None = None, maximum_messages: int | None = None) -> int:
        topology = self.engine.topology()
        snapshot = await self.admin.stream_info(self.hub_endpoint_name, topology.hub_archive.name)
        if snapshot.messages == 0:
            return 0
        first = snapshot.first_sequence if start_sequence is None else max(start_sequence, snapshot.first_sequence)
        last = snapshot.last_sequence
        if maximum_messages is not None:
            last = min(last, first + maximum_messages - 1)
        inserted = 0
        for sequence in range(first, last + 1):
            try:
                raw = await self.admin.get_message_by_sequence(
                    self.hub_endpoint_name,
                    topology.hub_archive.name,
                    sequence,
                )
            except JsonApiError:
                continue
            try:
                document = json.loads(raw.data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(document, Mapping):
                continue
            try:
                event = EventEnvelope.from_mapping(document)
            except Exception:
                continue
            record = ArchiveRecord(
                identity=event.identity,
                hub_stream_sequence=raw.sequence,
                payload_sha256=event.payload_sha256,
                archived_at=raw.time,
                source_stream=str(raw.headers.get("Nats-Stream-Source", self.engine.expected_stream_for_event(event))),
                source_domain=str(raw.headers.get("X-Origin-Domain", self.engine.region_config(event.identity.region)["domain"])),
            )
            if self.engine.store.upsert_archive_record(record):
                inserted += 1
        return inserted


class LabProcessManager:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.run_dir = self.root / "run"
        self.log_dir = self.root / "log" / "runtime"
        self.config_dir = self.root / "config" / "nats"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for name in ("hub", "east", "west"):
            (self.root / "state" / "nats" / name).mkdir(parents=True, exist_ok=True)

    def _pid_file(self, name: str) -> Path:
        return self.run_dir / f"{name}.pid"

    def _log_file(self, name: str) -> Path:
        return self.log_dir / f"{name}.log"

    def _read_pid(self, name: str) -> int | None:
        path = self._pid_file(name)
        if not path.exists():
            return None
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def status(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name in ("hub", "east", "west"):
            pid = self._read_pid(name)
            result[name] = {"pid": pid, "running": bool(pid and self._alive(pid))}
        return result

    def start_one(self, name: str) -> int:
        current = self._read_pid(name)
        if current is not None and self._alive(current):
            return current
        config = self.config_dir / f"{name}.conf"
        if not config.exists():
            raise ContractError(f"NATS config missing: {config}")
        log_path = self._log_file(name)
        log_handle = log_path.open("ab", buffering=0)
        process = subprocess.Popen(
            ["nats-server", "-c", str(config)],
            cwd=self.root,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._pid_file(name).write_text(str(process.pid) + "\n", encoding="utf-8")
        return process.pid

    def start_all(self) -> dict[str, int]:
        result: dict[str, int] = {}
        result["hub"] = self.start_one("hub")
        time.sleep(0.8)
        result["east"] = self.start_one("east")
        result["west"] = self.start_one("west")
        return result

    def stop_one(self, name: str, *, timeout: float = 5.0) -> None:
        pid = self._read_pid(name)
        if pid is None:
            return
        if self._alive(pid):
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and self._alive(pid):
                time.sleep(0.05)
            if self._alive(pid):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except OSError:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
        try:
            self._pid_file(name).unlink()
        except FileNotFoundError:
            pass

    def stop_all(self) -> None:
        for name in ("east", "west", "hub"):
            self.stop_one(name)

    def wait_monitor(self, url: str, *, timeout: float = 10.0) -> Mapping[str, Any]:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url.rstrip("/") + "/varz", timeout=0.5) as response:
                    document = json.loads(response.read().decode("utf-8"))
                if isinstance(document, Mapping):
                    return document
            except Exception as exc:
                last_error = exc
                time.sleep(0.1)
        raise ContractError(f"NATS monitor {url} did not become ready: {last_error}")

    def wait_all(self, *, timeout: float = 10.0) -> dict[str, Mapping[str, Any]]:
        return {
            "hub": self.wait_monitor("http://127.0.0.1:8222", timeout=timeout),
            "east": self.wait_monitor("http://127.0.0.1:8223", timeout=timeout),
            "west": self.wait_monitor("http://127.0.0.1:8224", timeout=timeout),
        }


def endpoints_from_engine(engine: ContinuityEngine) -> dict[str, NatsEndpoint]:
    hub = engine.config.get("hub")
    if not isinstance(hub, Mapping):
        raise ContractError("configuration has no hub endpoint")
    result = {
        "hub": NatsEndpoint(
            name="hub",
            url=str(hub["server_url"]),
            domain=str(hub["domain"]),
            monitor_url=str(hub["monitor_url"]),
        )
    }
    for region in ("east", "west"):
        cfg = engine.region_config(region)
        result[region] = NatsEndpoint(
            name=region,
            url=str(cfg["server_url"]),
            domain=str(cfg["domain"]),
            monitor_url=str(cfg["monitor_url"]),
        )
    return result
