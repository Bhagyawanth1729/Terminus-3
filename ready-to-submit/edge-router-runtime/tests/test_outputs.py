from __future__ import annotations

import copy
import http.client
import json
import signal
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

APP = Path("/app/edge-router")
BINARY = Path("/tmp/edge-router-runtime-verifier")
HOST = "service.test"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Backend:
    def __init__(self, name: str, *, response_status: int = 200, health_status: int = 200):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.name = name
        self.response_status = response_status
        self.health_status = health_status
        self.block_path: str | None = None
        self.started = threading.Event()
        self.release = threading.Event()
        self.requests: list[str] = []
        self.port = free_port()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                owner.requests.append(self.path)
                if self.path == "/healthz":
                    payload = b"health"
                    status = owner.health_status
                else:
                    if owner.block_path and self.path.startswith(owner.block_path):
                        owner.started.set()
                        owner.release.wait(timeout=8)
                    payload = json.dumps({"backend": owner.name, "path": self.path}).encode()
                    status = owner.response_status
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.port}"

    def start(self) -> "Backend":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


@pytest.fixture(scope="session", autouse=True)
def build_binary() -> None:
    subprocess.run(
        ["go", "build", "-o", str(BINARY), "./cmd/edge-router-runtime"],
        cwd=APP,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@contextmanager
def running_backends(*items: Backend):
    started = [item.start() for item in items]
    try:
        yield started
    finally:
        for item in started:
            item.stop()


def endpoint(address: str, *, weight: int = 1, zone: str = "z1", label: str = "") -> dict:
    value = {"address": address, "weight": weight, "zone": zone}
    if label:
        value["metadata"] = {"label": label}
    return value


def document(
    endpoints: list[dict],
    *,
    generation: int = 1,
    strategy: str = "round_robin",
    route_affinity: str = "none",
    pool_metadata: dict[str, str] | None = None,
    failover_endpoints: list[dict] | None = None,
    health_interval_ms: int = 1000,
    health_timeout_ms: int = 250,
    unhealthy_threshold: int = 1,
    drain_timeout_ms: int = 1200,
) -> dict:
    affinity = {"mode": "none"}
    if route_affinity == "header":
        affinity = {
            "mode": "header",
            "header": "X-Session-Key",
            "ttl_seconds": 120,
            "capacity": 64,
        }
    pool = {
        "id": "primary",
        "strategy": strategy,
        "endpoints": endpoints,
        "health": {
            "path": "/healthz",
            "interval_ms": health_interval_ms,
            "timeout_ms": health_timeout_ms,
            "healthy_threshold": 1,
            "unhealthy_threshold": unhealthy_threshold,
            "expected_statuses": [200],
        },
        "transport": {
            "scheme": "http",
            "max_idle_conns": 32,
            "max_idle_conns_per_host": 8,
            "idle_conn_timeout_ms": 1000,
            "tls_insecure_skip_verify": False,
        },
        "affinity": {"mode": "none"},
    }
    if pool_metadata is not None:
        pool["metadata"] = pool_metadata
    pools = [pool]
    failovers: list[str] = []
    if failover_endpoints is not None:
        failovers = ["failover"]
        fallback = copy.deepcopy(pool)
        fallback["id"] = "failover"
        fallback["endpoints"] = failover_endpoints
        pools.append(fallback)
    return {
        "schema_version": 1,
        "generation": generation,
        "sources": [{"name": "bootstrap", "revision": generation, "digest": ""}],
        "defaults": {
            "connect_timeout_ms": 300,
            "request_timeout_ms": 2500,
            "drain_timeout_ms": drain_timeout_ms,
            "health_interval_ms": health_interval_ms,
            "health_timeout_ms": health_timeout_ms,
            "affinity_ttl_seconds": 120,
            "affinity_capacity": 64,
        },
        "pools": pools,
        "routes": [
            {
                "id": "route-main",
                "hosts": [HOST],
                "path_prefix": "/api",
                "methods": ["GET"],
                "pool": "primary",
                "failover_pools": failovers,
                "retry": {
                    "attempts": 3,
                    "per_try_timeout_ms": 800,
                    "retry_on": ["connect-error", "5xx", "reset"],
                },
                "affinity": affinity,
                "headers": [],
                "priority": 100,
            }
        ],
    }


def http_json(port: int, method: str, path: str, body: dict | None = None, headers=None):
    payload = None if body is None else json.dumps(body).encode()
    req_headers = dict(headers or {})
    if payload is not None:
        req_headers["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=6)
    conn.request(method, path, body=payload, headers=req_headers)
    response = conn.getresponse()
    raw = response.read()
    result_headers = dict(response.getheaders())
    status = response.status
    conn.close()
    parsed = None
    if raw:
        try:
            parsed = json.loads(raw.decode())
        except json.JSONDecodeError:
            parsed = raw.decode(errors="replace")
    return status, parsed, result_headers


def wait_ready(port: int, *, timeout: float = 6.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            status, body, _ = http_json(port, "GET", "/ready")
            last = (status, body)
            if status == 200 and isinstance(body, dict) and body.get("ready") is True:
                return body
        except OSError as exc:
            last = exc
        time.sleep(0.04)
    raise AssertionError(f"runtime never became ready: {last}")


def status(admin_port: int) -> dict:
    code, body, _ = http_json(admin_port, "GET", "/v1/status")
    assert code == 200
    assert isinstance(body, dict)
    return body


def pool_status(admin_port: int, pool_id: str = "primary") -> dict:
    pools = status(admin_port)["runtime"]["pools"]
    return next(pool for pool in pools if pool["id"] == pool_id)


def wait_pool(admin_port: int, key: str, value: int, timeout: float = 4.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = pool_status(admin_port)
        if int(last.get(key, -1)) == value:
            return last
        time.sleep(0.05)
    raise AssertionError(f"pool {key} did not reach {value}: {last}")


def submit(admin_port: int, source: str, revision: int, body: dict):
    return http_json(admin_port, "POST", f"/v1/config?source={source}&revision={revision}", body)


def proxy(public_port: int, path: str = "/api/item", session: str | None = None):
    headers = {"Host": HOST}
    if session is not None:
        headers["X-Session-Key"] = session
    return http_json(public_port, "GET", path, headers=headers)


@contextmanager
def gateway(tmp_path: Path, doc: dict, *, state_dir: Path | None = None):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(doc), encoding="utf-8")
    state = state_dir or (tmp_path / "state")
    state.mkdir(parents=True, exist_ok=True)
    public_port = free_port()
    admin_port = free_port()
    proc = subprocess.Popen(
        [
            str(BINARY),
            "serve",
            "--config",
            str(config_path),
            "--state-dir",
            str(state),
            "--listen",
            f"127.0.0.1:{public_port}",
            "--admin-listen",
            f"127.0.0.1:{admin_port}",
        ],
        cwd=APP,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_ready(admin_port)
        yield {
            "proc": proc,
            "public": public_port,
            "admin": admin_port,
            "state": state,
            "config": config_path,
        }
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)


def backend_name(result) -> str:
    code, body, _ = result
    assert code == 200, body
    assert isinstance(body, dict)
    return str(body["backend"])


def current_generation(admin_port: int) -> int:
    return int(status(admin_port)["runtime"]["generation"])


def accepted_revision(admin_port: int, source: str) -> int:
    return int(status(admin_port)["reconciler"]["accepted_revisions"].get(source, 0))


def mutate_priority(doc: dict, priority: int) -> dict:
    changed = copy.deepcopy(doc)
    changed["routes"][0]["priority"] = priority
    return changed


def newest_and_previous(state_dir: Path) -> tuple[Path, Path]:
    bodies = sorted(state_dir.glob("generation-*.json"), reverse=True)
    assert len(bodies) >= 2
    return bodies[0], bodies[1]


# F2P: generation fencing and accepted-state transactionality.
def test_f2p_same_revision_different_digest_is_conflict(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        with gateway(tmp_path, doc) as gw:
            code, body, _ = submit(gw["admin"], "config", 2, doc)
            assert code == 200 and body["outcome"] == "accepted"
            generation = current_generation(gw["admin"])
            code, body, _ = submit(gw["admin"], "config", 2, mutate_priority(doc, 101))
            assert code == 409
            assert body["outcome"] in {"conflict", "rejected", "stale"}
            assert current_generation(gw["admin"]) == generation


def test_f2p_exact_duplicate_is_generation_noop(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        with gateway(tmp_path, doc) as gw:
            code, _, _ = submit(gw["admin"], "config", 2, doc)
            assert code == 200
            generation = current_generation(gw["admin"])
            code, body, _ = submit(gw["admin"], "config", 2, doc)
            assert code == 200
            assert body["outcome"] in {"accepted", "duplicate", "noop"}
            assert current_generation(gw["admin"]) == generation


def test_p2p_stale_revision_cannot_publish(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        with gateway(tmp_path, doc) as gw:
            assert submit(gw["admin"], "config", 4, doc)[0] == 200
            generation = current_generation(gw["admin"])
            code, body, _ = submit(gw["admin"], "config", 3, mutate_priority(doc, 102))
            assert code == 409 and body["outcome"] == "stale"
            assert current_generation(gw["admin"]) == generation


def test_f2p_rejected_candidate_does_not_advance_fence(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        with gateway(tmp_path, doc) as gw:
            assert submit(gw["admin"], "config", 2, doc)[0] == 200
            bad = copy.deepcopy(doc)
            bad["routes"][0]["pool"] = "missing-pool"
            code, body, _ = submit(gw["admin"], "config", 3, bad)
            assert code == 409 and body["outcome"] == "rejected"
            assert accepted_revision(gw["admin"], "config") == 2
            assert submit(gw["admin"], "config", 3, mutate_priority(doc, 103))[0] == 200


def test_f2p_conflict_preserves_last_serving_digest(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        with gateway(tmp_path, doc) as gw:
            submit(gw["admin"], "config", 2, doc)
            before = status(gw["admin"])["runtime"]["digest"]
            submit(gw["admin"], "config", 2, mutate_priority(doc, 104))
            assert status(gw["admin"])["runtime"]["digest"] == before


# F2P: independent source authority and recovery fences.
def test_f2p_sources_have_independent_revision_sequences(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        with gateway(tmp_path, doc) as gw:
            assert submit(gw["admin"], "config", 100, doc)[0] == 200
            assert submit(gw["admin"], "discovery", 2, doc)[0] == 200
            assert accepted_revision(gw["admin"], "config") == 100
            assert accepted_revision(gw["admin"], "discovery") == 2


def test_f2p_low_revision_new_source_not_blocked_by_high_other_source(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        with gateway(tmp_path, doc) as gw:
            assert submit(gw["admin"], "config", 50, doc)[0] == 200
            code, body, _ = submit(gw["admin"], "inventory", 1, mutate_priority(doc, 106))
            assert code == 200 and body["outcome"] == "accepted"


def test_f2p_source_conflict_is_scoped_to_that_source(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        with gateway(tmp_path, doc) as gw:
            assert submit(gw["admin"], "config", 9, doc)[0] == 200
            assert submit(gw["admin"], "discovery", 10, doc)[0] == 200
            code, body, _ = submit(gw["admin"], "discovery", 10, mutate_priority(doc, 107))
            assert code == 409 and body["outcome"] == "conflict"
            assert accepted_revision(gw["admin"], "discovery") == 10
            code, body, _ = submit(gw["admin"], "config", 10, mutate_priority(doc, 108))
            assert code == 200 and body["outcome"] == "accepted"


def test_f2p_duplicate_one_source_does_not_poison_another(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        with gateway(tmp_path, doc) as gw:
            submit(gw["admin"], "config", 7, doc)
            submit(gw["admin"], "config", 7, doc)
            code, body, _ = submit(gw["admin"], "discovery", 1, mutate_priority(doc, 109))
            assert code == 200 and body["outcome"] == "accepted"


def test_f2p_recovered_source_fence_rejects_older_revision(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        state_dir = tmp_path / "durable"
        first = tmp_path / "first"
        first.mkdir()
        with gateway(first, doc, state_dir=state_dir) as gw:
            assert submit(gw["admin"], "discovery", 8, doc)[0] == 200
            assert submit(gw["admin"], "config", 100, mutate_priority(doc, 110))[0] == 200
        second = tmp_path / "second"
        second.mkdir()
        with gateway(second, doc, state_dir=state_dir) as gw:
            code, body, _ = submit(gw["admin"], "config", 99, mutate_priority(doc, 111))
            assert code == 409 and body["outcome"] == "stale"
            code, body, _ = submit(gw["admin"], "discovery", 9, mutate_priority(doc, 112))
            assert code == 200 and body["outcome"] == "accepted"


def test_f2p_bounded_ingress_retains_newest_complete_snapshot(tmp_path):
    probe = APP / "internal" / "config" / "zz_verifier_ingress_test.go"
    source = r'''
package config

import (
    "context"
    "encoding/json"
    "sync"
    "testing"
    "time"
)

type verifierBlockingProcessor struct {
    mu sync.Mutex
    revisions []uint64
    started chan struct{}
    release chan struct{}
}

func (p *verifierBlockingProcessor) Process(_ context.Context, candidate Candidate) SubmitResult {
    p.mu.Lock()
    p.revisions = append(p.revisions, candidate.Revision)
    first := len(p.revisions) == 1
    p.mu.Unlock()
    if first {
        close(p.started)
        <-p.release
    }
    return SubmitResult{Source: candidate.Source, Revision: candidate.Revision, Digest: candidate.Digest, Outcome: "accepted"}
}

func (p *verifierBlockingProcessor) maxRevision() uint64 {
    p.mu.Lock()
    defer p.mu.Unlock()
    var max uint64
    for _, revision := range p.revisions {
        if revision > max {
            max = revision
        }
    }
    return max
}

func verifierDocument(t *testing.T) []byte {
    t.Helper()
    doc := Document{
        SchemaVersion: 1,
        Defaults: Defaults{ConnectTimeoutMS: 300, RequestTimeoutMS: 2500, DrainTimeoutMS: 1200, HealthIntervalMS: 1000, HealthTimeoutMS: 250, AffinityTTLSeconds: 120, AffinityCapacity: 64},
        Pools: []Pool{{
            ID: "primary",
            Strategy: "round_robin",
            Endpoints: []Endpoint{{Address: "127.0.0.1:1", Weight: 1, Zone: "z1"}},
            Health: HealthPolicy{Path: "/healthz", IntervalMS: 1000, TimeoutMS: 250, HealthyThreshold: 1, UnhealthyThreshold: 1, ExpectedStatuses: []int{200}},
            Transport: TransportPolicy{Scheme: "http", MaxIdleConns: 32, MaxIdleConnsPerHost: 8, IdleConnTimeoutMS: 1000},
            Affinity: AffinityPolicy{Mode: "none"},
        }},
        Routes: []Route{{
            ID: "route-main",
            Hosts: []string{"service.test"},
            PathPrefix: "/api",
            Methods: []string{"GET"},
            Pool: "primary",
            Retry: RetryPolicy{Attempts: 1, PerTryTimeoutMS: 800, RetryOn: []string{"5xx"}},
            Affinity: AffinityPolicy{Mode: "none"},
            Priority: 100,
        }},
    }
    raw, err := json.Marshal(doc)
    if err != nil {
        t.Fatal(err)
    }
    return raw
}

func TestVerifierBoundedIngressRetainsNewest(t *testing.T) {
    ctx, cancel := context.WithCancel(context.Background())
    defer cancel()
    processor := &verifierBlockingProcessor{started: make(chan struct{}), release: make(chan struct{})}
    ingress := NewIngress(processor, 2)
    ingress.Start(ctx)
    raw := verifierDocument(t)

    var wg sync.WaitGroup
    submitAsync := func(revision uint64) {
        wg.Add(1)
        go func() {
            defer wg.Done()
            submitCtx, submitCancel := context.WithTimeout(ctx, 750*time.Millisecond)
            defer submitCancel()
            _, _ = ingress.Submit(submitCtx, "config", revision, raw)
        }()
    }

    submitAsync(1)
    select {
    case <-processor.started:
    case <-time.After(time.Second):
        t.Fatal("first candidate did not reach processor")
    }

    submitAsync(2)
    submitAsync(3)
    deadline := time.Now().Add(time.Second)
    for len(ingress.queue) < 2 && time.Now().Before(deadline) {
        time.Sleep(5 * time.Millisecond)
    }
    if len(ingress.queue) != 2 {
        t.Fatalf("queue did not fill: len=%d", len(ingress.queue))
    }

    submitAsync(4)
    time.Sleep(25 * time.Millisecond)
    close(processor.release)
    wg.Wait()

    deadline = time.Now().Add(time.Second)
    for processor.maxRevision() < 4 && time.Now().Before(deadline) {
        time.Sleep(5 * time.Millisecond)
    }
    if got := processor.maxRevision(); got != 4 {
        t.Fatalf("bounded ingress did not retain newest complete snapshot: max processed revision=%d want=4", got)
    }
}
'''
    probe.write_text(source, encoding="utf-8")
    try:
        result = subprocess.run(
            ["go", "test", "./internal/config", "-run", "TestVerifierBoundedIngressRetainsNewest", "-count=1"],
            cwd=APP,
            text=True,
            capture_output=True,
            timeout=20,
        )
    finally:
        probe.unlink(missing_ok=True)
    assert result.returncode == 0, result.stdout + result.stderr


# F2P: stable identity, semantic compatibility, and incarnation boundaries.
def test_f2p_canonical_duplicate_endpoint_identity_is_rejected(tmp_path):
    port = free_port()
    doc = document([endpoint(f"localhost:{port}"), endpoint(f"LOCALHOST.:{port}")])
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    result = subprocess.run(
        [str(BINARY), "validate", "--config", str(path)],
        cwd=APP,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0


def test_f2p_endpoint_reorder_preserves_sticky_continuity(tmp_path):
    with running_backends(Backend("a"), Backend("b")) as (a, b):
        doc = document([endpoint(a.address), endpoint(b.address)], route_affinity="header")
        with gateway(tmp_path, doc) as gw:
            assert backend_name(proxy(gw["public"], session="sticky")) == "a"
            changed = copy.deepcopy(doc)
            changed["pools"][0]["endpoints"].reverse()
            assert submit(gw["admin"], "config", 2, changed)[0] == 200
            assert backend_name(proxy(gw["public"], session="sticky")) == "a"


def test_f2p_nonsemantic_pool_metadata_preserves_sticky_state(tmp_path):
    with running_backends(Backend("a"), Backend("b")) as (a, b):
        doc = document([endpoint(a.address), endpoint(b.address)], route_affinity="header")
        with gateway(tmp_path, doc) as gw:
            assert backend_name(proxy(gw["public"])) == "a"
            assert backend_name(proxy(gw["public"], session="sticky")) == "b"
            changed = copy.deepcopy(doc)
            changed["pools"][0]["metadata"] = {"deployment": "green"}
            assert submit(gw["admin"], "config", 2, changed)[0] == 200
            assert backend_name(proxy(gw["public"], session="sticky")) == "b"


def test_f2p_equivalent_address_format_preserves_sticky_state(tmp_path):
    with running_backends(Backend("a"), Backend("b")) as (a, b):
        doc = document(
            [endpoint(f"localhost:{a.port}"), endpoint(b.address)],
            route_affinity="header",
        )
        with gateway(tmp_path, doc) as gw:
            assert backend_name(proxy(gw["public"])) == "a"
            assert backend_name(proxy(gw["public"], session="sticky")) == "b"
            changed = copy.deepcopy(doc)
            changed["pools"][0]["endpoints"][0]["address"] = f"LOCALHOST.:{a.port}"
            assert submit(gw["admin"], "config", 2, changed)[0] == 200
            assert backend_name(proxy(gw["public"], session="sticky")) == "b"


def test_f2p_selection_policy_change_resets_balancer_state(tmp_path):
    with running_backends(Backend("a"), Backend("b")) as (a, b):
        doc = document([endpoint(a.address), endpoint(b.address)])
        with gateway(tmp_path, doc) as gw:
            assert backend_name(proxy(gw["public"])) == "a"
            changed = copy.deepcopy(doc)
            changed["pools"][0]["strategy"] = "weighted"
            assert submit(gw["admin"], "config", 2, changed)[0] == 200
            assert backend_name(proxy(gw["public"])) == "a"


def test_f2p_remove_readd_does_not_reuse_old_unhealthy_incarnation(tmp_path):
    a = Backend("a", health_status=503)
    b = Backend("b")
    with running_backends(a, b):
        doc = document([endpoint(a.address)], health_interval_ms=1000)
        with gateway(tmp_path, doc) as gw:
            wait_pool(gw["admin"], "unhealthy", 1)
            removed = document([endpoint(b.address)], health_interval_ms=5000)
            assert submit(gw["admin"], "config", 2, removed)[0] == 200
            a.health_status = 200
            readded = document([endpoint(a.address)], health_interval_ms=5000)
            assert submit(gw["admin"], "config", 3, readded)[0] == 200
            assert pool_status(gw["admin"])["unhealthy"] == 0


# F2P: leased-generation selection and eligibility.
def test_f2p_sticky_affinity_revalidates_unhealthy_endpoint(tmp_path):
    a = Backend("a")
    b = Backend("b")
    with running_backends(a, b):
        doc = document([endpoint(a.address), endpoint(b.address)], route_affinity="header")
        with gateway(tmp_path, doc) as gw:
            assert backend_name(proxy(gw["public"], session="s")) == "a"
            a.health_status = 503
            wait_pool(gw["admin"], "unhealthy", 1)
            assert backend_name(proxy(gw["public"], session="s")) == "b"


def test_f2p_all_unhealthy_backends_return_service_unavailable(tmp_path):
    a = Backend("a", health_status=503)
    b = Backend("b", health_status=503)
    with running_backends(a, b):
        doc = document([endpoint(a.address), endpoint(b.address)])
        with gateway(tmp_path, doc) as gw:
            wait_pool(gw["admin"], "unhealthy", 2)
            code, _body, _ = proxy(gw["public"])
            assert code == 503
            assert not any(path.startswith("/api") for path in a.requests + b.requests)


def test_f2p_retry_exclusion_survives_runtime_object_replacement(tmp_path):
    a = Backend("a", response_status=503)
    b = Backend("b")
    with running_backends(a, b):
        a.block_path = "/api"
        doc = document([endpoint(a.address), endpoint(b.address)], pool_metadata={"v": "1"})
        with gateway(tmp_path, doc) as gw:
            result: dict[str, tuple] = {}

            def make_request():
                result["value"] = proxy(gw["public"])

            thread = threading.Thread(target=make_request)
            thread.start()
            assert a.started.wait(timeout=3)
            changed = copy.deepcopy(doc)
            changed["pools"][0]["metadata"] = {"v": "2"}
            assert submit(gw["admin"], "config", 2, changed)[0] == 200
            a.release.set()
            thread.join(timeout=5)
            assert backend_name(result["value"]) == "b"
            assert sum(path.startswith("/api") for path in a.requests) == 1


def test_f2p_failover_uses_request_leased_generation(tmp_path):
    a = Backend("a", response_status=503)
    old_fallback = Backend("old-fallback")
    new_fallback = Backend("new-fallback")
    with running_backends(a, old_fallback, new_fallback):
        a.block_path = "/api"
        doc = document([endpoint(a.address)], failover_endpoints=[endpoint(old_fallback.address)])
        with gateway(tmp_path, doc) as gw:
            result: dict[str, tuple] = {}
            thread = threading.Thread(target=lambda: result.setdefault("value", proxy(gw["public"])))
            thread.start()
            assert a.started.wait(timeout=3)
            changed = copy.deepcopy(doc)
            changed["pools"][1]["id"] = "new-failover"
            changed["pools"][1]["endpoints"] = [endpoint(new_fallback.address)]
            changed["routes"][0]["failover_pools"] = ["new-failover"]
            assert submit(gw["admin"], "config", 2, changed)[0] == 200
            a.release.set()
            thread.join(timeout=5)
            assert backend_name(result["value"]) == "old-fallback"


# F2P/P2P: lifecycle ownership and bounded observability.
def test_p2p_removed_endpoint_is_not_used_for_fresh_requests(tmp_path):
    with running_backends(Backend("a"), Backend("b")) as (a, b):
        doc = document([endpoint(a.address)])
        with gateway(tmp_path, doc) as gw:
            assert backend_name(proxy(gw["public"])) == "a"
            changed = document([endpoint(b.address)])
            assert submit(gw["admin"], "config", 2, changed)[0] == 200
            assert backend_name(proxy(gw["public"])) == "b"


def test_p2p_inflight_request_survives_unrelated_publication(tmp_path):
    a = Backend("a")
    b = Backend("b")
    with running_backends(a, b):
        a.block_path = "/api/hold"
        doc = document([endpoint(a.address)])
        with gateway(tmp_path, doc) as gw:
            result: dict[str, tuple] = {}
            thread = threading.Thread(
                target=lambda: result.setdefault("value", proxy(gw["public"], "/api/hold"))
            )
            thread.start()
            assert a.started.wait(timeout=3)
            assert submit(gw["admin"], "config", 2, document([endpoint(b.address)]))[0] == 200
            assert backend_name(proxy(gw["public"], "/api/new")) == "b"
            a.release.set()
            thread.join(timeout=5)
            assert backend_name(result["value"]) == "a"


def test_f2p_metric_scope_count_remains_bounded_under_churn(tmp_path):
    with running_backends(Backend("a"), Backend("b")) as (a, b):
        doc = document([endpoint(a.address)], drain_timeout_ms=100)
        with gateway(tmp_path, doc) as gw:
            for revision in range(2, 28):
                address = b.address if revision % 2 == 0 else a.address
                changed = document([endpoint(address)], drain_timeout_ms=100)
                assert submit(gw["admin"], "config", revision, changed)[0] == 200
            time.sleep(1.5)
            assert int(status(gw["admin"])["metric_scopes"]) <= 20


# F2P: durable checkpoint integrity and fallback.
def test_f2p_corrupt_current_body_falls_back_to_previous_complete_generation(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        state_dir = tmp_path / "state"
        first = tmp_path / "run1"
        first.mkdir()
        with gateway(first, doc, state_dir=state_dir) as gw:
            submit(gw["admin"], "config", 2, mutate_priority(doc, 120))
        newest, previous = newest_and_previous(state_dir)
        previous_generation = int(json.loads(previous.read_text())["generation"])
        newest.write_text("{", encoding="utf-8")
        second = tmp_path / "run2"
        second.mkdir()
        with gateway(second, doc, state_dir=state_dir) as gw:
            assert current_generation(gw["admin"]) == previous_generation


def test_f2p_corrupt_current_pointer_falls_back_to_previous_complete_generation(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        state_dir = tmp_path / "state"
        first = tmp_path / "run1"
        first.mkdir()
        with gateway(first, doc, state_dir=state_dir) as gw:
            submit(gw["admin"], "config", 2, mutate_priority(doc, 121))
        _newest, previous = newest_and_previous(state_dir)
        previous_generation = int(json.loads(previous.read_text())["generation"])
        (state_dir / "CURRENT").write_text("not-json", encoding="utf-8")
        second = tmp_path / "run2"
        second.mkdir()
        with gateway(second, doc, state_dir=state_dir) as gw:
            assert current_generation(gw["admin"]) == previous_generation


def test_f2p_checksum_mismatch_is_not_recovered_as_current(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        state_dir = tmp_path / "state"
        first = tmp_path / "run1"
        first.mkdir()
        with gateway(first, doc, state_dir=state_dir) as gw:
            submit(gw["admin"], "config", 2, mutate_priority(doc, 122))
        newest, previous = newest_and_previous(state_dir)
        previous_generation = int(json.loads(previous.read_text())["generation"])
        body = json.loads(newest.read_text())
        body["checksum"] = "0" * 64
        newest.write_text(json.dumps(body), encoding="utf-8")
        second = tmp_path / "run2"
        second.mkdir()
        with gateway(second, doc, state_dir=state_dir) as gw:
            assert current_generation(gw["admin"]) == previous_generation


def test_f2p_schema_incompatible_checkpoint_is_not_recovered(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        state_dir = tmp_path / "state"
        first = tmp_path / "run1"
        first.mkdir()
        with gateway(first, doc, state_dir=state_dir) as gw:
            submit(gw["admin"], "config", 2, mutate_priority(doc, 123))
        newest, previous = newest_and_previous(state_dir)
        previous_generation = int(json.loads(previous.read_text())["generation"])
        body = json.loads(newest.read_text())
        body["schema_version"] = 999
        newest.write_text(json.dumps(body), encoding="utf-8")
        second = tmp_path / "run2"
        second.mkdir()
        with gateway(second, doc, state_dir=state_dir) as gw:
            assert current_generation(gw["admin"]) == previous_generation


def test_p2p_missing_current_body_falls_back_to_retained_previous(tmp_path):
    with running_backends(Backend("a")) as (a,):
        doc = document([endpoint(a.address)])
        state_dir = tmp_path / "state"
        first = tmp_path / "run1"
        first.mkdir()
        with gateway(first, doc, state_dir=state_dir) as gw:
            submit(gw["admin"], "config", 2, mutate_priority(doc, 124))
        newest, previous = newest_and_previous(state_dir)
        previous_generation = int(json.loads(previous.read_text())["generation"])
        newest.unlink()
        second = tmp_path / "run2"
        second.mkdir()
        with gateway(second, doc, state_dir=state_dir) as gw:
            assert current_generation(gw["admin"]) == previous_generation


# P2P preservation probes for already-correct public interfaces.
def test_p2p_validate_accepts_normal_configuration(tmp_path):
    port = free_port()
    path = tmp_path / "valid.json"
    path.write_text(json.dumps(document([endpoint(f"127.0.0.1:{port}")])), encoding="utf-8")
    result = subprocess.run(
        [str(BINARY), "validate", "--config", str(path)], cwd=APP, text=True, capture_output=True
    )
    assert result.returncode == 0
    assert "configuration valid" in result.stdout


def test_p2p_validate_rejects_unknown_json_field(tmp_path):
    port = free_port()
    doc = document([endpoint(f"127.0.0.1:{port}")])
    doc["unknown_contract_field"] = True
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    result = subprocess.run(
        [str(BINARY), "validate", "--config", str(path)], cwd=APP, text=True, capture_output=True
    )
    assert result.returncode != 0


def test_p2p_health_ready_and_status_surfaces(tmp_path):
    with running_backends(Backend("a")) as (a,):
        with gateway(tmp_path, document([endpoint(a.address)])) as gw:
            assert http_json(gw["admin"], "GET", "/health")[0] == 200
            assert http_json(gw["admin"], "GET", "/ready")[0] == 200
            snapshot = status(gw["admin"])
            assert snapshot["runtime"]["routes"] == 1


def test_p2p_data_plane_proxies_request(tmp_path):
    with running_backends(Backend("a")) as (a,):
        with gateway(tmp_path, document([endpoint(a.address)])) as gw:
            assert backend_name(proxy(gw["public"], "/api/hello")) == "a"


def test_p2p_route_host_mismatch_returns_not_found(tmp_path):
    with running_backends(Backend("a")) as (a,):
        with gateway(tmp_path, document([endpoint(a.address)])) as gw:
            code, _body, _ = http_json(
                gw["public"], "GET", "/api/hello", headers={"Host": "other.test"}
            )
            assert code == 404


def test_p2p_metrics_and_events_are_operator_readable(tmp_path):
    with running_backends(Backend("a")) as (a,):
        with gateway(tmp_path, document([endpoint(a.address)])) as gw:
            proxy(gw["public"])
            code, metrics, headers = http_json(gw["admin"], "GET", "/metrics")
            assert code == 200
            assert "text/plain" in headers["Content-Type"]
            assert "edge_requests_total" in str(metrics)
            code, events, _ = http_json(gw["admin"], "GET", "/v1/events")
            assert code == 200 and isinstance(events["events"], list)
