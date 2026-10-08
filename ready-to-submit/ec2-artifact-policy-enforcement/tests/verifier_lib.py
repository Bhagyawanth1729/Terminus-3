from __future__ import annotations

import concurrent.futures
import copy
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(os.environ.get("ENFORCER_ROOT", "/app/enforcer"))
BIN = Path(os.environ.get("AG_BIN", "/usr/local/bin/artifactguard"))
NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def load_json(path: Path):
    return json.loads(path.read_text())


def base_policy():
    return load_json(ROOT / "config" / "policy.json")


def base_scans():
    return load_json(ROOT / "fixtures" / "scans.json")


def empty_exceptions():
    return {"exceptions": []}


def denied_severities(policy):
    return {str(value).lower() for value in policy["deny_severities"]}


def scan_is_vulnerable(record, policy):
    denied = denied_severities(policy)
    return any(str(v.get("severity", "")).lower() in denied for v in record.get("vulnerabilities", []))


def find_digest(*, vulnerable=None, status="ok"):
    policy = base_policy()
    for digest, record in base_scans()["records"].items():
        if record.get("status") != status:
            continue
        if status == "ok" and record.get("db_revision") != policy["scanner_db_revision"]:
            continue
        if vulnerable is None or scan_is_vulnerable(record, policy) == vulnerable:
            return digest
    raise AssertionError(f"fixture lacks digest status={status!r} vulnerable={vulnerable!r}")


def trusted_source(surface, policy=None):
    policy = policy or base_policy()
    values = policy["trusted_sources"][surface]
    assert values
    return values[0]


def other_surface(surface):
    return next(value for value in ("package", "container", "dependency") if value != surface)


def iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_request(request_id, surface, manager, digest, source, *, name="artifact", version="1.0", environment="staging", instance="i-verifier"):
    return {
        "request_id": request_id,
        "instance_id": instance,
        "environment": environment,
        "surface": surface,
        "manager": manager,
        "name": name,
        "version": version,
        "source": source,
        "digest": digest,
        "action": "install",
    }


def exception_for(req, *, digest=None, surfaces=None, environments=None, codes=None, expires=None, name=None):
    return {
        "id": "EX-VERIFIER",
        "name": req["name"] if name is None else name,
        "digest": req["digest"] if digest is None else digest,
        "surfaces": [req["surface"]] if surfaces is None else surfaces,
        "environments": [req["environment"]] if environments is None else environments,
        "policy_codes": ["VULNERABILITY_THRESHOLD"] if codes is None else codes,
        "expires_at": iso(NOW + timedelta(hours=2)) if expires is None else expires,
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


@contextmanager
def case_dir():
    with tempfile.TemporaryDirectory(prefix="artifactguard-verifier-") as td:
        yield Path(td)


def run_evaluate(work, req, *, state=None, policy=None, scans=None, exceptions=None, secret=b"verifier-secret-a", now=NOW):
    work.mkdir(parents=True, exist_ok=True)
    state = state or work / "state"
    policy = copy.deepcopy(policy or base_policy())
    scans = copy.deepcopy(scans or base_scans())
    exceptions = copy.deepcopy(exceptions or empty_exceptions())
    req_path = work / "request.json"
    policy_path = work / "policy.json"
    scans_path = work / "scans.json"
    exceptions_path = work / "exceptions.json"
    secret_path = work / "secret"
    write_json(req_path, req)
    write_json(policy_path, policy)
    write_json(scans_path, scans)
    write_json(exceptions_path, exceptions)
    secret_path.write_bytes(secret)
    cp = subprocess.run([
        str(BIN), "evaluate",
        "--request", str(req_path),
        "--policy", str(policy_path),
        "--scans", str(scans_path),
        "--exceptions", str(exceptions_path),
        "--state", str(state),
        "--secret", str(secret_path),
        "--now", iso(now),
    ], text=True, capture_output=True)
    output = json.loads(cp.stdout) if cp.stdout.strip() else None
    return cp, output, {
        "request": req_path,
        "policy": policy_path,
        "secret": secret_path,
        "state": Path(state),
    }


def run_verify(permit, req, policy, secret, *, work, state=None, now=NOW):
    work.mkdir(parents=True, exist_ok=True)
    permit_path = work / "permit.json"
    req_path = work / "request.json"
    policy_path = work / "policy.json"
    secret_path = work / "secret"
    write_json(permit_path, permit)
    write_json(req_path, req)
    write_json(policy_path, policy)
    secret_path.write_bytes(secret)
    cmd = [
        str(BIN), "verify-permit",
        "--permit", str(permit_path),
        "--request", str(req_path),
        "--policy", str(policy_path),
        "--secret", str(secret_path),
        "--now", iso(now),
    ]
    if state is not None:
        cmd.extend(["--state", str(state)])
    cp = subprocess.run(cmd, text=True, capture_output=True)
    output = json.loads(cp.stdout) if cp.stdout.strip() else None
    return cp, output


def assert_decision(cp, output, rc, code):
    assert cp.returncode == rc, (cp.returncode, cp.stdout, cp.stderr)
    assert output is not None, (cp.stdout, cp.stderr)
    assert output["code"] == code, output


def audit_records(state):
    path = Path(state) / "audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def issue_clean_permit(work, *, secret=b"verifier-secret-a", request_id="req-permit", instance="i-permit"):
    policy = base_policy()
    digest = find_digest(vulnerable=False)
    req = make_request(request_id, "package", "apt", digest, trusted_source("package", policy), instance=instance)
    cp, output, _ = run_evaluate(work, req, secret=secret)
    assert_decision(cp, output, 0, "ALLOW_CLEAN")
    assert output.get("permit")
    return output["permit"], req, policy


def changed_scan(scans, digest, *, status="ok", db_revision=None, vulnerable=None):
    result = copy.deepcopy(scans)
    record = copy.deepcopy(result["records"][digest])
    record["status"] = status
    if db_revision is not None:
        record["db_revision"] = db_revision
    if vulnerable is not None:
        if vulnerable:
            template_digest = find_digest(vulnerable=True)
            record["vulnerabilities"] = copy.deepcopy(base_scans()["records"][template_digest]["vulnerabilities"])
        else:
            record["vulnerabilities"] = []
    result["records"][digest] = record
    return result


def run_two_verifications(permit, req, policy, secret, state, work):
    def one(index):
        return run_verify(permit, req, policy, secret, work=work / f"v{index}", state=state)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(one, range(2)))
