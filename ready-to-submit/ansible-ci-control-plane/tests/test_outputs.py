"""Behavioural verification of the deployed CI control plane.

The deployment artifacts collected from the agent environment are the input:
the compiled binary, the rendered configuration, the supervisor program
definition, the persisted state tree and the deployment report. The service is
started from those artifacts on a scratch state directory and driven over HTTP.
"""

from __future__ import annotations

import configparser
import concurrent.futures
import hashlib
import json
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests

PREFIX = Path("/app/var/ci-server")
BINARY = PREFIX / "bin" / "ci-server"
CONFIG = PREFIX / "etc" / "ci-server.json"
PROGRAM = PREFIX / "etc" / "supervisor" / "ci-server.conf"
STATE = PREFIX / "state"
LOGS = PREFIX / "logs"
REPORT = STATE / "deploy-report.json"

CONFIG_KEYS = {
    "listen",
    "state_dir",
    "log_dir",
    "api_token",
    "webhook_token",
    "agent_ttl_seconds",
    "default_page_size",
    "max_page_size",
    "build_retention",
    "log_chunk_max_bytes",
    "claim_lease_seconds",
    "max_log_chunks",
    "build_timeout_seconds",
    "default_max_concurrent",
    "version",
}
STATE_SUBDIRS = (
    "pipelines",
    "builds",
    "artifacts",
    "agents",
    "logs",
    "steps",
    "audit",
    "idempotency",
)

PIPELINE_ID = re.compile(r"^pl-\d{6}$")
BUILD_ID = re.compile(r"^bd-\d{6}$")
AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$")
TRUTHY = {"true", "yes", "on", "1"}
HTTP_TIMEOUT = 10


def deployed_config() -> dict:
    """Parse the configuration document the deployment rendered."""
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class CiServer:
    """A control-plane process started from the deployed binary."""

    def __init__(self, workdir: Path, overrides: dict):
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.state_dir = workdir / "state"
        self.log_dir = workdir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.port = _free_port()

        config = deployed_config()
        config["listen"] = f"127.0.0.1:{self.port}"
        config["state_dir"] = str(self.state_dir)
        config["log_dir"] = str(self.log_dir)
        config.update(overrides)
        self.config = config

        self.config_path = workdir / "ci-server.json"
        self.config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        self.exe = workdir / "ci-server"
        shutil.copy2(BINARY, self.exe)
        self.exe.chmod(0o755)

        self.output_path = workdir / "ci-server.log"
        self.proc: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def auth(self) -> dict:
        return {"X-Ci-Server-Token": self.config["api_token"]}

    @property
    def hook_auth(self) -> dict:
        return {"X-Ci-Server-Webhook-Token": self.config["webhook_token"]}

    def start(self) -> "CiServer":
        handle = self.output_path.open("a", encoding="utf-8")
        self.proc = subprocess.Popen(
            [str(self.exe), "-config", str(self.config_path)],
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(
                    "ci-server exited with code "
                    f"{self.proc.returncode}: {self.output_path.read_text(encoding='utf-8')}"
                )
            try:
                if requests.get(f"{self.url}/healthz", timeout=2).status_code == 200:
                    return self
            except requests.RequestException:
                pass
            time.sleep(0.1)
        raise AssertionError(
            "ci-server never answered /healthz: "
            + self.output_path.read_text(encoding="utf-8")
        )

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=15)
        self.proc = None

    def restart(self) -> "CiServer":
        self.stop()
        return self.start()


@pytest.fixture
def ci_server_factory(tmp_path):
    """Start control-plane processes on scratch state, tearing them down after."""
    started: list[CiServer] = []

    def _start(**overrides) -> CiServer:
        node = CiServer(tmp_path / f"node-{len(started)}", overrides)
        started.append(node)
        return node.start()

    yield _start

    for node in started:
        node.stop()


@pytest.fixture
def ci_server(ci_server_factory) -> CiServer:
    """A control plane running with the deployed settings on scratch state."""
    return ci_server_factory()


def register(node: CiServer, name: str, branch: str = "main", **kwargs):
    body = {
        "name": name,
        "repo": f"git@vcs.internal:platform/{name}.git",
        "default_branch": branch,
    }
    return requests.post(
        f"{node.url}/v1/pipelines",
        json=body,
        headers=kwargs.get("headers", node.auth),
        timeout=HTTP_TIMEOUT,
    )


def trigger(node: CiServer, name: str, branch: str | None = None):
    body = {} if branch is None else {"branch": branch}
    return requests.post(
        f"{node.url}/v1/hooks/{name}",
        json=body,
        headers=node.hook_auth,
        timeout=HTTP_TIMEOUT,
    )


def set_status(node: CiServer, build_id: str, status: str, reason: str | None = None):
    body: dict = {"status": status}
    if reason is not None:
        body["reason"] = reason
    return requests.post(
        f"{node.url}/v1/builds/{build_id}/status",
        json=body,
        headers=node.auth,
        timeout=HTTP_TIMEOUT,
    )


def heartbeat(node: CiServer, agent_id: str = "runner-01", capacity: int = 3):
    return requests.post(
        f"{node.url}/v1/agents/heartbeat",
        json={"agent_id": agent_id, "capacity": capacity},
        headers=node.auth,
        timeout=HTTP_TIMEOUT,
    )


def claim_build(node: CiServer, build_id: str, agent_id: str = "runner-01", capacity: int = 3):
    """Claim after ensuring the agent is online with spare capacity."""
    assert heartbeat(node, agent_id, capacity).status_code == 200
    return requests.post(
        f"{node.url}/v1/builds/{build_id}/claim",
        json={"agent_id": agent_id},
        headers=node.auth,
        timeout=HTTP_TIMEOUT,
    )


def append_log(node: CiServer, build_id: str, seq: int, text: str = "line"):
    return requests.post(
        f"{node.url}/v1/builds/{build_id}/logs",
        json={"seq": seq, "text": text},
        headers=node.auth,
        timeout=HTTP_TIMEOUT,
    )


def add_artifact(node: CiServer, build_id: str, path: str, digest: str | None = None):
    return requests.post(
        f"{node.url}/v1/builds/{build_id}/artifacts",
        json={
            "path": path,
            "size_bytes": 1024,
            "sha256": digest if digest is not None else "a" * 64,
        },
        headers=node.auth,
        timeout=HTTP_TIMEOUT,
    )


def queued_build(node: CiServer, pipeline: str) -> str:
    register(node, pipeline)
    response = trigger(node, pipeline)
    assert response.status_code == 202, response.text
    return response.json()["build_id"]


# --------------------------------------------------------------------------
# Deployment artifacts
# --------------------------------------------------------------------------


def test_deployment_installs_the_control_plane_tree():
    """The deployment leaves a compiled binary, config, program file and state tree."""
    assert BINARY.is_file(), f"{BINARY} is missing"
    assert BINARY.stat().st_size > 0
    assert BINARY.read_bytes()[:4] == b"\x7fELF", f"{BINARY} is not a compiled binary"
    assert CONFIG.is_file(), f"{CONFIG} is missing"
    assert PROGRAM.is_file(), f"{PROGRAM} is missing"
    assert LOGS.is_dir(), f"{LOGS} is missing"
    for sub in STATE_SUBDIRS:
        assert (STATE / sub).is_dir(), f"{STATE / sub} is missing"


def test_rendered_configuration_matches_the_contract():
    """The rendered configuration carries exactly the contract keys and values."""
    config = deployed_config()
    assert set(config) == CONFIG_KEYS, f"unexpected key set: {sorted(config)}"
    assert config["listen"] == "127.0.0.1:8080"
    assert config["state_dir"] == str(STATE)
    assert config["log_dir"] == str(LOGS)
    assert config["agent_ttl_seconds"] == 45
    assert config["default_page_size"] == 5
    assert config["max_page_size"] == 50
    assert config["build_retention"] == 3
    assert config["log_chunk_max_bytes"] == 4096
    assert config["claim_lease_seconds"] == 120
    assert config["max_log_chunks"] == 100
    assert config["build_timeout_seconds"] == 600
    assert config["default_max_concurrent"] == 2
    assert config["version"] == "3.1.0"
    assert isinstance(config["api_token"], str) and config["api_token"]
    assert isinstance(config["webhook_token"], str) and config["webhook_token"]
    assert config["api_token"] != config["webhook_token"]


def test_supervisor_program_definition_runs_the_deployed_binary():
    """The supervisor program named ci_server runs the deployed binary as the service account."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read(PROGRAM, encoding="utf-8")
    assert "program:ci-server" in parser.sections(), parser.sections()

    section = parser["program:ci-server"]
    command = section["command"]
    assert command.split()[0] == str(BINARY), command
    assert str(CONFIG) in command, command
    assert section["user"].strip() == "ciserver"
    assert section["autostart"].strip().lower() in TRUTHY
    assert section["autorestart"].strip().lower() in TRUTHY
    assert str(LOGS) in section["stdout_logfile"]
    assert str(LOGS) in section["stderr_logfile"]


def test_deployment_report_comes_from_the_live_control_plane():
    """The report mirrors the deployed configuration and every smoke check succeeded."""
    config = deployed_config()
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert set(report) == {"status", "version", "listen", "config_digest", "checks"}
    assert report["status"] == "ok"
    assert report["version"] == config["version"]
    assert report["listen"] == config["listen"]

    digest = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    assert report["config_digest"] == digest, "report digest does not match the deployed config bytes"

    checks = report["checks"]
    assert set(checks) == {
        "health",
        "pipeline_registered",
        "webhook_build",
        "build_claimed",
        "log_appended",
        "step_recorded",
        "status_transition",
        "artifact_recorded",
        "agent_registered",
        "audit_total",
        "metrics_running",
    }
    assert checks["health"] == "ok"
    assert checks["pipeline_registered"] in {"201", "409"}
    assert BUILD_ID.match(checks["webhook_build"]), checks["webhook_build"]
    assert checks["build_claimed"] == "bootstrap-runner"
    assert checks["log_appended"] == "1"
    assert checks["step_recorded"] == "bootstrap"
    assert checks["status_transition"] == "running"
    assert AGENT_ID.match(checks["agent_registered"]), checks["agent_registered"]
    assert checks["audit_total"].isdigit() and int(checks["audit_total"]) >= 1
    assert checks["metrics_running"] == "1"

    artifact_path = checks["artifact_recorded"]
    assert artifact_path and not artifact_path.startswith("/")
    assert ".." not in artifact_path.split("/")


def test_persisted_state_backs_the_deployment_report():
    """The records on disk describe the same build, artifact and runner as the report."""
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    checks = report["checks"]
    build_id = checks["webhook_build"]

    build = json.loads((STATE / "builds" / f"{build_id}.json").read_text(encoding="utf-8"))
    assert build["id"] == build_id
    assert build["status"] == "running"
    assert build["claimed_by"] == checks["build_claimed"]
    assert isinstance(build["claimed_at"], int) and build["claimed_at"] > 0
    assert PIPELINE_ID.match(build["pipeline_id"]), build["pipeline_id"]
    assert build["pipeline_name"]

    pipeline_record = STATE / "pipelines" / f"{build['pipeline_id']}.json"
    pipeline = json.loads(pipeline_record.read_text(encoding="utf-8"))
    assert pipeline["id"] == build["pipeline_id"]
    assert pipeline["name"] == build["pipeline_name"]

    artifacts = json.loads((STATE / "artifacts" / f"{build_id}.json").read_text(encoding="utf-8"))
    assert [a["path"] for a in artifacts] == [checks["artifact_recorded"]]

    log_chunk = json.loads((STATE / "logs" / build_id / "000001.json").read_text(encoding="utf-8"))
    assert log_chunk["seq"] == 1
    assert log_chunk["text"]
    assert log_chunk["build_id"] == build_id

    steps = json.loads((STATE / "steps" / f"{build_id}.json").read_text(encoding="utf-8"))
    assert steps[0]["name"] == checks["step_recorded"]
    assert steps[0]["status"] == "running"

    audit_files = sorted((STATE / "audit").glob("*.json"))
    assert len(audit_files) == int(checks["audit_total"])

    agent_record = STATE / "agents" / f"{checks['agent_registered']}.json"
    assert json.loads(agent_record.read_text(encoding="utf-8"))["agent_id"] == checks["agent_registered"]


# --------------------------------------------------------------------------
# Service behaviour
# --------------------------------------------------------------------------


def test_health_reflects_the_configuration_it_was_started_with(ci_server_factory):
    """Health reports the version, listen address and byte digest of its own config file."""
    node = ci_server_factory(version="9.9.9-scratch")
    body = requests.get(f"{node.url}/healthz", timeout=HTTP_TIMEOUT).json()

    assert body["status"] == "ok"
    assert body["version"] == "9.9.9-scratch"
    assert body["listen"] == node.config["listen"]
    assert body["pipelines"] == 0
    assert body["queued_builds"] == 0
    assert body["config_digest"] == hashlib.sha256(node.config_path.read_bytes()).hexdigest()

    register(node, "svc-health")
    trigger(node, "svc-health")
    after = requests.get(f"{node.url}/healthz", timeout=HTTP_TIMEOUT).json()
    assert after["pipelines"] == 1
    assert after["queued_builds"] == 1


def test_writes_require_the_api_credential(ci_server):
    """State-changing requests need the configured API token and reject the webhook one."""
    anonymous = register(ci_server, "svc-anon", headers={})
    assert anonymous.status_code == 401
    assert anonymous.json()["error"] == "unauthorized"

    wrong = register(ci_server, "svc-anon", headers={"X-Ci-Server-Token": "not-the-token"})
    assert wrong.status_code == 401

    crossed = register(
        ci_server, "svc-anon", headers={"X-Ci-Server-Token": ci_server.config["webhook_token"]}
    )
    assert crossed.status_code == 401

    accepted = register(ci_server, "svc-anon")
    assert accepted.status_code == 201, accepted.text


def test_webhook_uses_its_own_credential(ci_server):
    """The webhook entry point accepts only the webhook token, in the webhook header."""
    register(ci_server, "svc-hook")
    url = f"{ci_server.url}/v1/hooks/svc-hook"

    anonymous = requests.post(url, json={}, timeout=HTTP_TIMEOUT)
    assert anonymous.status_code == 401
    assert anonymous.json()["error"] == "unauthorized"

    api_in_hook_header = requests.post(
        url,
        json={},
        headers={"X-Ci-Server-Webhook-Token": ci_server.config["api_token"]},
        timeout=HTTP_TIMEOUT,
    )
    assert api_in_hook_header.status_code == 401

    hook_in_api_header = requests.post(
        url,
        json={},
        headers={"X-Ci-Server-Token": ci_server.config["webhook_token"]},
        timeout=HTTP_TIMEOUT,
    )
    assert hook_in_api_header.status_code == 401

    accepted = requests.post(url, json={}, headers=ci_server.hook_auth, timeout=HTTP_TIMEOUT)
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert BUILD_ID.match(body["build_id"])
    assert PIPELINE_ID.match(body["pipeline_id"])
    assert body["status"] == "queued"
    assert body["branch"] == "main"


def test_pipeline_names_are_unique_ignoring_case(ci_server):
    """A name already taken under any casing is refused, and bad names are rejected."""
    assert register(ci_server, "Payments-Api").status_code == 201

    clash = register(ci_server, "payments-api")
    assert clash.status_code == 409
    assert clash.json()["error"] == "pipeline_exists"

    invalid = register(ci_server, "payments api!")
    assert invalid.status_code == 400
    assert invalid.json()["error"] == "invalid_pipeline_name"


def test_pagination_is_one_based_and_reports_the_whole_total(ci_server_factory):
    """Listings page from one using the configured page size and report the full count."""
    node = ci_server_factory(default_page_size=2, max_page_size=4)
    names = ["svc-a", "svc-b", "svc-c", "svc-d", "svc-e"]
    for name in names:
        assert register(node, name).status_code == 201

    first = requests.get(f"{node.url}/v1/pipelines", timeout=HTTP_TIMEOUT).json()
    assert [p["name"] for p in first["items"]] == names[:2]
    assert first["page"] == 1
    assert first["per_page"] == 2
    assert first["total"] == 5

    second = requests.get(
        f"{node.url}/v1/pipelines", params={"page": 2, "per_page": 2}, timeout=HTTP_TIMEOUT
    ).json()
    assert [p["name"] for p in second["items"]] == names[2:4]
    assert second["total"] == 5

    beyond = requests.get(
        f"{node.url}/v1/pipelines", params={"page": 9, "per_page": 2}, timeout=HTTP_TIMEOUT
    ).json()
    assert beyond["items"] == []
    assert beyond["total"] == 5


def test_pagination_arguments_outside_the_configured_range_are_refused(ci_server_factory):
    """Page and per_page values outside the configured bounds are rejected."""
    node = ci_server_factory(default_page_size=2, max_page_size=4)
    for params in ({"per_page": 5}, {"page": 0}, {"per_page": 0}, {"page": "later"}):
        response = requests.get(
            f"{node.url}/v1/pipelines", params=params, timeout=HTTP_TIMEOUT
        )
        assert response.status_code == 400, f"{params} -> {response.status_code}"
        assert response.json()["error"] == "invalid_pagination"

    allowed = requests.get(
        f"{node.url}/v1/pipelines", params={"per_page": 4}, timeout=HTTP_TIMEOUT
    )
    assert allowed.status_code == 200


def test_queue_is_an_array_even_when_nothing_is_queued(ci_server):
    """An idle control plane answers the queue with an empty array and a zero count."""
    body = requests.get(f"{ci_server.url}/v1/queue", timeout=HTTP_TIMEOUT).json()
    assert body["items"] == []
    assert body["count"] == 0


def test_queue_lists_queued_builds_in_arrival_order(ci_server):
    """Queued builds appear in queue-sequence order and claimed ones drop out."""
    register(ci_server, "svc-queue")
    ids = [trigger(ci_server, "svc-queue").json()["build_id"] for _ in range(3)]
    assert claim_build(ci_server, ids[0]).status_code == 200

    body = requests.get(f"{ci_server.url}/v1/queue", timeout=HTTP_TIMEOUT).json()
    assert [b["id"] for b in body["items"]] == ids[1:]
    assert body["count"] == 2
    assert all(b["status"] == "queued" for b in body["items"])
    assert all(b["pipeline_name"] == "svc-queue" for b in body["items"])


def test_outcomes_are_only_reachable_through_running(ci_server):
    """A queued build cannot claim an outcome via status; claim is required to start."""
    build = queued_build(ci_server, "svc-machine")

    skipped = set_status(ci_server, build, "success")
    assert skipped.status_code == 409
    assert skipped.json()["error"] == "invalid_transition"

    via_status = set_status(ci_server, build, "running")
    assert via_status.status_code == 409
    assert via_status.json()["error"] == "invalid_transition"

    started = claim_build(ci_server, build, "runner-machine")
    assert started.status_code == 200
    assert started.json()["status"] == "running"
    assert started.json()["claimed_by"] == "runner-machine"

    duplicate = claim_build(ci_server, build, "other-runner")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "already_claimed"

    missing_reason = set_status(ci_server, build, "canceled")
    assert missing_reason.status_code == 400
    assert missing_reason.json()["error"] == "invalid_cancel_reason"

    canceled = set_status(ci_server, build, "canceled", reason="runner lost")
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    assert canceled.json()["cancel_reason"] == "runner lost"

    revived = set_status(ci_server, build, "running")
    assert revived.status_code == 409
    assert revived.json()["error"] == "invalid_transition"

    unknown_status = set_status(ci_server, build, "exploded")
    assert unknown_status.status_code == 400
    assert unknown_status.json()["error"] == "invalid_status"

    unknown_build = claim_build(ci_server, "bd-999999")
    assert unknown_build.status_code == 404
    assert unknown_build.json()["error"] == "build_not_found"


def test_log_chunks_are_ordered_and_only_while_running(ci_server):
    """Log chunks require a running build, start at seq 1, and refuse gaps or duplicates."""
    build = queued_build(ci_server, "svc-logs")

    early = append_log(ci_server, build, 1, "too soon")
    assert early.status_code == 409
    assert early.json()["error"] == "build_not_running"

    assert claim_build(ci_server, build).status_code == 200

    bad_start = append_log(ci_server, build, 2, "skip")
    assert bad_start.status_code == 409
    assert bad_start.json()["error"] == "invalid_log_seq"

    first = append_log(ci_server, build, 1, "hello")
    assert first.status_code == 201, first.text
    assert first.json()["seq"] == 1
    assert first.json()["text"] == "hello"

    duplicate = append_log(ci_server, build, 1, "again")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "invalid_log_seq"

    second = append_log(ci_server, build, 2, "world")
    assert second.status_code == 201, second.text

    listing = requests.get(f"{ci_server.url}/v1/builds/{build}/logs", timeout=HTTP_TIMEOUT).json()
    assert [c["seq"] for c in listing["items"]] == [1, 2]
    assert listing["count"] == 2

    oversized = append_log(ci_server, build, 3, "x" * (ci_server.config["log_chunk_max_bytes"] + 1))
    assert oversized.status_code == 400
    assert oversized.json()["error"] == "invalid_log_chunk"


def test_finished_builds_are_purged_beyond_retention(ci_server_factory):
    """Oldest finished builds disappear once the retention ceiling is exceeded."""
    node = ci_server_factory(build_retention=2)
    register(node, "svc-retain")
    ids = []
    for index in range(3):
        build_id = trigger(node, "svc-retain").json()["build_id"]
        ids.append(build_id)
        assert claim_build(node, build_id, f"runner-{index}").status_code == 200
        assert append_log(node, build_id, 1, f"log-{index}").status_code == 201
        assert set_status(node, build_id, "success").status_code == 200

    remaining = sorted(p.stem for p in (node.state_dir / "builds").glob("*.json"))
    assert remaining == ids[1:]
    assert not (node.state_dir / "builds" / f"{ids[0]}.json").exists()
    assert not (node.state_dir / "logs" / ids[0]).exists()
    assert (node.state_dir / "logs" / ids[1]).is_dir()
    assert (node.state_dir / "logs" / ids[2]).is_dir()


def test_artifacts_belong_to_builds_that_have_started(ci_server):
    """Artifact metadata is refused while a build is queued and deduplicated afterwards."""
    build = queued_build(ci_server, "svc-artifacts")

    early = add_artifact(ci_server, build, "logs/build.txt")
    assert early.status_code == 409
    assert early.json()["error"] == "build_not_started"

    assert claim_build(ci_server, build).status_code == 200

    created = add_artifact(ci_server, build, "logs/build.txt")
    assert created.status_code == 201, created.text
    assert created.json()["build_id"] == build
    assert created.json()["path"] == "logs/build.txt"

    duplicate = add_artifact(ci_server, build, "logs/build.txt")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "artifact_exists"

    listing = requests.get(
        f"{ci_server.url}/v1/builds/{build}/artifacts", timeout=HTTP_TIMEOUT
    ).json()
    assert [a["path"] for a in listing["items"]] == ["logs/build.txt"]
    assert listing["count"] == 1


def test_artifact_keys_that_escape_the_build_namespace_are_refused(ci_server):
    """Absolute, traversing, backslashed and malformed artifact keys are rejected."""
    build = queued_build(ci_server, "svc-escape")
    assert claim_build(ci_server, build).status_code == 200

    for path in (
        "",
        "/etc/shadow",
        "../outside.txt",
        "logs/../../etc/shadow",
        "logs/./out.txt",
        "logs//out.txt",
        "logs\\out.txt",
        "a/" * 120 + "deep.txt",
    ):
        response = add_artifact(ci_server, build, path)
        assert response.status_code == 400, f"{path!r} -> {response.status_code}"
        assert response.json()["error"] == "invalid_artifact_path"

    bad_digest = add_artifact(ci_server, build, "logs/ok.txt", digest="not-a-digest")
    assert bad_digest.status_code == 400
    assert bad_digest.json()["error"] == "invalid_artifact_digest"

    upper_digest = add_artifact(ci_server, build, "logs/ok.txt", digest="A" * 64)
    assert upper_digest.status_code == 400


def test_runners_go_offline_after_the_configured_lifetime(ci_server_factory):
    """A runner is listed while its heartbeat is fresh and disappears once it expires."""
    node = ci_server_factory(agent_ttl_seconds=2)

    beat = requests.post(
        f"{node.url}/v1/agents/heartbeat",
        json={"agent_id": "runner-01", "capacity": 3},
        headers=node.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert beat.status_code == 200, beat.text
    assert beat.json()["expires_in_seconds"] == 2
    assert beat.json()["capacity"] == 3

    online = requests.get(f"{node.url}/v1/agents", timeout=HTTP_TIMEOUT).json()
    assert online["count"] == 1
    assert online["items"][0]["agent_id"] == "runner-01"
    assert online["items"][0]["state"] == "online"

    time.sleep(4)

    expired = requests.get(f"{node.url}/v1/agents", timeout=HTTP_TIMEOUT).json()
    assert expired["items"] == []
    assert expired["count"] == 0


def test_identifiers_keep_counting_across_a_restart(ci_server):
    """Restarting the control plane resumes the identifier sequences instead of reusing them."""
    assert register(ci_server, "svc-one").json()["id"] == "pl-000001"
    assert register(ci_server, "svc-two").json()["id"] == "pl-000002"
    first_build = queued_build(ci_server, "svc-three")
    assert first_build == "bd-000001"

    ci_server.restart()

    resumed = register(ci_server, "svc-four")
    assert resumed.status_code == 201
    assert resumed.json()["id"] == "pl-000004"
    assert resumed.json()["created_seq"] == 4

    later_build = trigger(ci_server, "svc-four").json()["build_id"]
    assert later_build == "bd-000002"

    listing = requests.get(f"{ci_server.url}/v1/pipelines", timeout=HTTP_TIMEOUT).json()
    assert listing["total"] == 4


def test_paused_pipelines_reject_webhooks(ci_server):
    """A paused pipeline refuses new webhook builds until it is resumed."""
    assert register(ci_server, "svc-pause").status_code == 201
    pipeline_id = requests.get(f"{ci_server.url}/v1/pipelines", timeout=HTTP_TIMEOUT).json()["items"][0]["id"]

    paused = requests.post(
        f"{ci_server.url}/v1/pipelines/{pipeline_id}/pause",
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert paused.status_code == 200
    assert paused.json()["paused"] is True

    blocked = trigger(ci_server, "svc-pause")
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "pipeline_paused"

    resumed = requests.post(
        f"{ci_server.url}/v1/pipelines/{pipeline_id}/resume",
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False
    assert trigger(ci_server, "svc-pause").status_code == 202


def test_webhook_params_are_validated_and_persisted(ci_server):
    """Webhook params are validated and stored on the queued build."""
    register(ci_server, "svc-params")
    bad = requests.post(
        f"{ci_server.url}/v1/hooks/svc-params",
        json={"params": {"bad key": "x"}},
        headers=ci_server.hook_auth,
        timeout=HTTP_TIMEOUT,
    )
    assert bad.status_code == 400
    assert bad.json()["error"] == "invalid_params"

    ok = requests.post(
        f"{ci_server.url}/v1/hooks/svc-params",
        json={"params": {"ENV": "staging"}},
        headers=ci_server.hook_auth,
        timeout=HTTP_TIMEOUT,
    )
    assert ok.status_code == 202, ok.text
    assert ok.json()["params"] == {"ENV": "staging"}
    build = requests.get(
        f"{ci_server.url}/v1/builds/{ok.json()['build_id']}", timeout=HTTP_TIMEOUT
    ).json()
    assert build["params"] == {"ENV": "staging"}


def test_failed_builds_can_be_retried(ci_server):
    """Retry clones a failed build into a new queued build with retried_from set."""
    build = queued_build(ci_server, "svc-retry")
    assert claim_build(ci_server, build).status_code == 200
    assert set_status(ci_server, build, "failed").status_code == 200

    retried = requests.post(
        f"{ci_server.url}/v1/builds/{build}/retry",
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert retried.status_code == 201, retried.text
    body = retried.json()
    assert body["status"] == "queued"
    assert body["trigger"] == "retry"
    assert body["retried_from"] == build
    assert body["id"] != build


def test_claim_lease_expires_when_the_runner_is_offline(ci_server_factory):
    """An expired claim returns the build to the queue once the runner is offline."""
    node = ci_server_factory(agent_ttl_seconds=1, claim_lease_seconds=1)
    build = queued_build(node, "svc-lease")
    assert claim_build(node, build, "lease-runner").status_code == 200
    time.sleep(2)
    queue = requests.get(f"{node.url}/v1/queue", timeout=HTTP_TIMEOUT).json()
    assert [b["id"] for b in queue["items"]] == [build]
    again = requests.get(f"{node.url}/v1/builds/{build}", timeout=HTTP_TIMEOUT).json()
    assert again["status"] == "queued"
    assert "claimed_by" not in again or not again.get("claimed_by")


def test_webhook_idempotency_returns_the_same_build(ci_server):
    """A repeated Idempotency-Key for the same pipeline reuses the original build."""
    register(ci_server, "svc-idem")
    headers = {**ci_server.hook_auth, "Idempotency-Key": "smoke-key-1"}
    first = requests.post(
        f"{ci_server.url}/v1/hooks/svc-idem", json={}, headers=headers, timeout=HTTP_TIMEOUT
    )
    second = requests.post(
        f"{ci_server.url}/v1/hooks/svc-idem", json={}, headers=headers, timeout=HTTP_TIMEOUT
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["build_id"] == second.json()["build_id"]


def test_queue_orders_by_priority_then_arrival(ci_server):
    """Higher priority queued builds appear before lower priority ones."""
    register(ci_server, "svc-prio")
    low = requests.post(
        f"{ci_server.url}/v1/hooks/svc-prio",
        json={"priority": 10},
        headers=ci_server.hook_auth,
        timeout=HTTP_TIMEOUT,
    ).json()["build_id"]
    high = requests.post(
        f"{ci_server.url}/v1/hooks/svc-prio",
        json={"priority": 90},
        headers=ci_server.hook_auth,
        timeout=HTTP_TIMEOUT,
    ).json()["build_id"]
    queue = requests.get(f"{ci_server.url}/v1/queue", timeout=HTTP_TIMEOUT).json()
    assert [b["id"] for b in queue["items"]] == [high, low]


def test_claim_respects_agent_capacity(ci_server):
    """An agent cannot claim more running builds than its capacity."""
    register(ci_server, "svc-cap")
    assert heartbeat(ci_server, "tiny-runner", capacity=1).status_code == 200
    first = trigger(ci_server, "svc-cap").json()["build_id"]
    second = trigger(ci_server, "svc-cap").json()["build_id"]
    ok = requests.post(
        f"{ci_server.url}/v1/builds/{first}/claim",
        json={"agent_id": "tiny-runner"},
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert ok.status_code == 200
    blocked = requests.post(
        f"{ci_server.url}/v1/builds/{second}/claim",
        json={"agent_id": "tiny-runner"},
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "agent_at_capacity"


def test_metrics_reflect_live_counts(ci_server):
    """Metrics report live counts after reclaiming expired work."""
    build = queued_build(ci_server, "svc-metrics")
    assert claim_build(ci_server, build).status_code == 200
    metrics = requests.get(
        f"{ci_server.url}/v1/metrics", headers=ci_server.auth, timeout=HTTP_TIMEOUT
    ).json()
    assert metrics["pipelines"] >= 1
    assert metrics["running_builds"] == 1
    assert metrics["queued_builds"] == 0
    assert metrics["online_agents"] >= 1
    assert metrics["audit_events"] >= 1


def test_audit_log_records_mutating_operations(ci_server):
    """Mutating operations append audit events that can be listed."""
    build = queued_build(ci_server, "svc-audit")
    assert claim_build(ci_server, build).status_code == 200
    listing = requests.get(f"{ci_server.url}/v1/audit", timeout=HTTP_TIMEOUT).json()
    actions = {item["action"] for item in listing["items"]}
    assert "pipeline_created" in actions or "build_queued" in actions
    assert "build_claimed" in actions
    assert listing["total"] >= 2


def test_queued_builds_can_be_canceled_without_claiming(ci_server):
    """A queued build may move to canceled through the status endpoint."""
    build = queued_build(ci_server, "svc-cancel-queued")
    canceled = set_status(ci_server, build, "canceled", reason="no longer needed")
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "canceled"
    assert canceled.json()["cancel_reason"] == "no longer needed"


def test_pipeline_rejects_disallowed_branches(ci_server):
    """Webhooks for branches outside allowed_branches are refused."""
    created = requests.post(
        f"{ci_server.url}/v1/pipelines",
        json={
            "name": "svc-branches",
            "repo": "git@vcs.internal:platform/svc-branches.git",
            "default_branch": "main",
            "allowed_branches": ["main", "release"],
        },
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert created.status_code == 201, created.text

    blocked = trigger(ci_server, "svc-branches", branch="feature/x")
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "branch_not_allowed"
    assert trigger(ci_server, "svc-branches", branch="main").status_code == 202


def test_claim_respects_pipeline_concurrency(ci_server):
    """A pipeline rejects claims once max_concurrent running builds is reached."""
    created = requests.post(
        f"{ci_server.url}/v1/pipelines",
        json={
            "name": "svc-pipe-cap",
            "repo": "git@vcs.internal:platform/svc-pipe-cap.git",
            "default_branch": "main",
            "max_concurrent": 1,
        },
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert created.status_code == 201, created.text
    first = trigger(ci_server, "svc-pipe-cap").json()["build_id"]
    second = trigger(ci_server, "svc-pipe-cap").json()["build_id"]
    assert claim_build(ci_server, first, "cap-runner-a").status_code == 200
    blocked = claim_build(ci_server, second, "cap-runner-b")
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "pipeline_at_capacity"


def test_running_builds_time_out(ci_server_factory):
    """Builds that stay running past build_timeout_seconds become failed."""
    node = ci_server_factory(build_timeout_seconds=1, claim_lease_seconds=3600)
    build = queued_build(node, "svc-timeout")
    assert claim_build(node, build, "timeout-runner").status_code == 200
    time.sleep(2)
    metrics = requests.get(
        f"{node.url}/v1/metrics", headers=node.auth, timeout=HTTP_TIMEOUT
    )
    assert metrics.status_code == 200, metrics.text
    body = requests.get(f"{node.url}/v1/builds/{build}", timeout=HTTP_TIMEOUT).json()
    assert body["status"] == "failed"
    audit = requests.get(f"{node.url}/v1/audit", timeout=HTTP_TIMEOUT).json()
    assert any(item["action"] == "build_timed_out" for item in audit["items"])


def test_log_chunk_limit_is_enforced(ci_server_factory):
    """Appending past max_log_chunks is refused with log_limit_reached."""
    node = ci_server_factory(max_log_chunks=2)
    build = queued_build(node, "svc-logcap")
    assert claim_build(node, build).status_code == 200
    assert append_log(node, build, 1, "one").status_code == 201
    assert append_log(node, build, 2, "two").status_code == 201
    blocked = append_log(node, build, 3, "three")
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "log_limit_reached"


def test_step_endpoint_validates_and_lists(ci_server):
    """Step writes validate name/status; reads return recorded steps."""
    build = queued_build(ci_server, "svc-steps")
    assert claim_build(ci_server, build).status_code == 200

    bad_name = requests.post(
        f"{ci_server.url}/v1/builds/{build}/steps",
        json={"name": "bad name", "status": "running"},
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert bad_name.status_code == 400
    assert bad_name.json()["error"] == "invalid_step_name"

    bad_status = requests.post(
        f"{ci_server.url}/v1/builds/{build}/steps",
        json={"name": "compile", "status": "weird"},
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert bad_status.status_code == 400
    assert bad_status.json()["error"] == "invalid_step_status"

    ok = requests.post(
        f"{ci_server.url}/v1/builds/{build}/steps",
        json={"name": "compile", "status": "running"},
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["name"] == "compile"

    listing = requests.get(
        f"{ci_server.url}/v1/builds/{build}/steps", timeout=HTTP_TIMEOUT
    ).json()
    assert listing["count"] == 1
    assert listing["items"][0]["name"] == "compile"
    assert listing["items"][0]["status"] == "running"


def test_pipeline_create_validates_repo_and_concurrency(ci_server):
    """Pipeline create refuses an empty repo and a non-positive max_concurrent."""
    empty_repo = requests.post(
        f"{ci_server.url}/v1/pipelines",
        json={"name": "svc-badrepo", "repo": "   ", "default_branch": "main"},
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert empty_repo.status_code == 400
    assert empty_repo.json()["error"] == "invalid_repo"

    bad_max = requests.post(
        f"{ci_server.url}/v1/pipelines",
        json={
            "name": "svc-badmax",
            "repo": "git@vcs.internal:platform/svc-badmax.git",
            "default_branch": "main",
            "max_concurrent": 0,
        },
        headers=ci_server.auth,
        timeout=HTTP_TIMEOUT,
    )
    assert bad_max.status_code == 400
    assert bad_max.json()["error"] == "invalid_max_concurrent"


def test_pipeline_and_build_reads_return_stored_records(ci_server):
    """GET /v1/pipelines/{id} and GET /v1/builds/{id}/steps serve stored records."""
    created = register(ci_server, "svc-getters")
    assert created.status_code == 201
    pipeline_id = created.json()["id"]

    fetched = requests.get(
        f"{ci_server.url}/v1/pipelines/{pipeline_id}", timeout=HTTP_TIMEOUT
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == pipeline_id
    assert fetched.json()["name"] == "svc-getters"

    missing = requests.get(
        f"{ci_server.url}/v1/pipelines/pl-999999", timeout=HTTP_TIMEOUT
    )
    assert missing.status_code == 404
    assert missing.json()["error"] == "pipeline_not_found"

    build = trigger(ci_server, "svc-getters").json()["build_id"]
    assert claim_build(ci_server, build).status_code == 200
    assert (
        requests.post(
            f"{ci_server.url}/v1/builds/{build}/steps",
            json={"name": "bootstrap", "status": "success"},
            headers=ci_server.auth,
            timeout=HTTP_TIMEOUT,
        ).status_code
        == 201
    )
    steps = requests.get(
        f"{ci_server.url}/v1/builds/{build}/steps", timeout=HTTP_TIMEOUT
    ).json()
    assert steps["count"] == 1
    assert steps["items"][0]["name"] == "bootstrap"


def test_service_refuses_a_configuration_it_cannot_trust(tmp_path):
    """Startup fails on an empty, duplicated or unknown-key configuration."""
    base = deployed_config()
    broken = [
        {"api_token": ""},
        {"webhook_token": ""},
        {"webhook_token": base["api_token"]},
        {"agent_ttl_seconds": 0},
        {"build_retention": 0},
        {"log_chunk_max_bytes": 0},
        {"claim_lease_seconds": 0},
        {"max_log_chunks": 0},
        {"build_timeout_seconds": 0},
        {"default_max_concurrent": 0},
        {"surprise": "extra"},
    ]

    for index, override in enumerate(broken):
        workdir = tmp_path / f"reject-{index}"
        workdir.mkdir()
        config = dict(base)
        config["listen"] = f"127.0.0.1:{_free_port()}"
        config["state_dir"] = str(workdir / "state")
        config["log_dir"] = str(workdir / "logs")
        config.update(override)

        config_path = workdir / "ci-server.json"
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        exe = workdir / "ci-server"
        shutil.copy2(BINARY, exe)
        exe.chmod(0o755)

        completed = subprocess.run(
            [str(exe), "-config", str(config_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode != 0, f"{override} was accepted"


def test_concurrent_identical_webhooks_converge_on_one_build(ci_server):
    """A storm of identical Idempotency-Key webhooks must create only one build."""
    register(ci_server, "svc-storm")
    headers = {**ci_server.hook_auth, "Idempotency-Key": "storm-key-1"}

    def fire(_):
        return requests.post(
            f"{ci_server.url}/v1/hooks/svc-storm",
            json={},
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(fire, range(8)))

    assert all(r.status_code == 202 for r in responses), [r.text for r in responses]
    build_ids = {r.json()["build_id"] for r in responses}
    assert len(build_ids) == 1
    queue = requests.get(f"{ci_server.url}/v1/queue", timeout=HTTP_TIMEOUT).json()
    assert sum(1 for item in queue["items"] if item["id"] in build_ids) == 1


def test_concurrent_claims_leave_one_winner(ci_server):
    """Two runners racing the same queued build leave exactly one claim holder."""
    build = queued_build(ci_server, "svc-race")
    assert heartbeat(ci_server, "racer-a", capacity=2).status_code == 200
    assert heartbeat(ci_server, "racer-b", capacity=2).status_code == 200

    def claim(agent_id: str):
        return requests.post(
            f"{ci_server.url}/v1/builds/{build}/claim",
            json={"agent_id": agent_id},
            headers=ci_server.auth,
            timeout=HTTP_TIMEOUT,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(claim, "racer-a")
        second = pool.submit(claim, "racer-b")
        responses = [first.result(), second.result()]

    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 409], [(r.status_code, r.text) for r in responses]
    winners = [r for r in responses if r.status_code == 200]
    losers = [r for r in responses if r.status_code == 409]
    assert losers[0].json()["error"] == "already_claimed"
    holder = winners[0].json()["claimed_by"]
    assert holder in {"racer-a", "racer-b"}
    current = requests.get(f"{ci_server.url}/v1/builds/{build}", timeout=HTTP_TIMEOUT).json()
    assert current["status"] == "running"
    assert current["claimed_by"] == holder


def test_claim_lease_expires_while_the_runner_stays_online(ci_server_factory):
    """Wall-clock lease expiry returns the build to the queue even if heartbeats continue."""
    node = ci_server_factory(agent_ttl_seconds=30, claim_lease_seconds=1)
    build = queued_build(node, "svc-lease-online")
    assert claim_build(node, build, "sticky-runner").status_code == 200

    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline:
        assert heartbeat(node, "sticky-runner", capacity=2).status_code == 200
        time.sleep(0.2)

    queue = requests.get(f"{node.url}/v1/queue", timeout=HTTP_TIMEOUT).json()
    assert [b["id"] for b in queue["items"]] == [build]
    again = requests.get(f"{node.url}/v1/builds/{build}", timeout=HTTP_TIMEOUT).json()
    assert again["status"] == "queued"

    blocked = append_log(node, build, 1, "too-late")
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "build_not_running"

    reclaim = claim_build(node, build, "sticky-runner")
    assert reclaim.status_code == 200
    assert reclaim.json()["status"] == "running"
    assert append_log(node, build, 1, "after-reclaim").status_code == 201


def test_claim_expiry_precedes_timeout_when_both_limits_are_reached(ci_server_factory):
    """A build returns to the queue when claim lease and build timeout expire together."""
    node = ci_server_factory(
        agent_ttl_seconds=30,
        claim_lease_seconds=1,
        build_timeout_seconds=1,
    )
    build = queued_build(node, "svc-expiry-order")
    assert claim_build(node, build, "expiry-runner").status_code == 200

    time.sleep(2)

    queue = requests.get(f"{node.url}/v1/queue", timeout=HTTP_TIMEOUT).json()
    assert [item["id"] for item in queue["items"]] == [build]
    current = requests.get(f"{node.url}/v1/builds/{build}", timeout=HTTP_TIMEOUT).json()
    assert current["status"] == "queued"
    audit = requests.get(f"{node.url}/v1/audit", timeout=HTTP_TIMEOUT).json()
    actions = [item["action"] for item in audit["items"]]
    assert "claim_expired" in actions
    assert "build_timed_out" not in actions


def test_claimed_build_survives_a_process_restart(ci_server_factory):
    """A claimed build remains running with the same holder after the process restarts."""
    node = ci_server_factory()
    build = queued_build(node, "svc-restart-claim")
    claimed = claim_build(node, build, "persistent-runner")
    assert claimed.status_code == 200
    holder = claimed.json()["claimed_by"]

    node.restart()

    restored = requests.get(f"{node.url}/v1/builds/{build}", timeout=HTTP_TIMEOUT).json()
    assert restored["status"] == "running"
    assert restored["claimed_by"] == holder
    assert append_log(node, build, 1, "post-restart").status_code == 201
