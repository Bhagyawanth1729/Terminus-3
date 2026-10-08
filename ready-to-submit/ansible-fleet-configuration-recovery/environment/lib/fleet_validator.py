from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
import argparse
import json
import re
import yaml
from state_engine import HostState

class Finding:
    def __init__(self, code: str, message: str, host: str = "", path: str = "", severity: str = "error"):
        self.code = code
        self.message = message
        self.host = host
        self.path = path
        self.severity = severity
    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "host": self.host, "path": self.path, "severity": self.severity}

def read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)

def rootfs(root: Path, host: str, absolute: str) -> Path:
    return root / "rootfs" / host / absolute.lstrip("/")

def validate_identity(root: Path, host: str, findings: list[Finding]) -> None:
    path = rootfs(root, host, "/etc/fleet/identity.json")
    if not path.is_file():
        findings.append(Finding("IDENTITY_MISSING", "identity document is missing", host, str(path)))
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        findings.append(Finding("IDENTITY_JSON", f"identity JSON cannot be parsed: {exc}", host, str(path)))
        return
    for key in ("host", "site", "environment", "service_account"):
        if not data.get(key):
            findings.append(Finding("IDENTITY_FIELD", f"identity field {key} is empty", host, str(path)))

def validate_trust(root: Path, host: str, findings: list[Finding]) -> None:
    path = rootfs(root, host, "/etc/ssl/certs/fleet-ca-bundle.pem")
    if not path.is_file():
        findings.append(Finding("TRUST_MISSING", "trust bundle is missing", host, str(path)))
        return
    text = path.read_text(encoding="utf-8")
    begins = text.count("-----BEGIN CERTIFICATE-----")
    ends = text.count("-----END CERTIFICATE-----")
    if begins == 0 or begins != ends:
        findings.append(Finding("TRUST_PEM", "trust bundle has invalid PEM boundaries", host, str(path)))

def validate_application(root: Path, host: str, findings: list[Finding]) -> None:
    path = rootfs(root, host, "/etc/fleet/application.yml")
    if not path.is_file():
        findings.append(Finding("APP_MISSING", "application configuration is missing", host, str(path)))
        return
    try:
        data = read_yaml(path)
    except Exception as exc:
        findings.append(Finding("APP_YAML", f"application YAML cannot be parsed: {exc}", host, str(path)))
        return
    if not isinstance(data, Mapping):
        findings.append(Finding("APP_SHAPE", "application document must be a mapping", host, str(path)))
        return
    for key in ("environment", "site", "service", "listen", "dependencies"):
        if key not in data:
            findings.append(Finding("APP_FIELD", f"application key {key} is missing", host, str(path)))
    listen = data.get("listen", {})
    if isinstance(listen, Mapping):
        try:
            port = int(listen.get("port", 0))
            if not 1 <= port <= 65535:
                raise ValueError()
        except Exception:
            findings.append(Finding("APP_PORT", "application listen port is invalid", host, str(path)))
    dependencies = data.get("dependencies", [])
    if not isinstance(dependencies, list):
        findings.append(Finding("APP_DEPENDENCIES", "dependencies must be a list", host, str(path)))

def parse_proxy_servers(text: str) -> list[tuple[str, int]]:
    servers = []
    for match in re.finditer(r"\bserver\s+([^;\s]+)", text):
        token = match.group(1)
        if token.startswith("[") and "]:" in token:
            host, port = token[1:].split("]:", 1)
        elif token.count(":") == 1:
            host, port = token.rsplit(":", 1)
        else:
            continue
        try:
            servers.append((host, int(port)))
        except ValueError:
            pass
    return servers

def validate_proxy(root: Path, host: str, findings: list[Finding]) -> None:
    path = rootfs(root, host, "/etc/nginx/conf.d/fleet.conf")
    if not path.is_file():
        findings.append(Finding("PROXY_MISSING", "proxy configuration is missing", host, str(path)))
        return
    text = path.read_text(encoding="utf-8")
    if text.count("{") != text.count("}"):
        findings.append(Finding("PROXY_BRACES", "proxy braces are not balanced", host, str(path)))
    servers = parse_proxy_servers(text)
    if not servers:
        findings.append(Finding("PROXY_BACKENDS", "proxy has no backend servers", host, str(path)))
    seen = set()
    for address, port in servers:
        if (address, port) in seen:
            findings.append(Finding("PROXY_DUPLICATE", f"duplicate proxy backend {address}:{port}", host, str(path)))
        seen.add((address, port))
        if ":" in address and f"[{address}]:{port}" not in text:
            findings.append(Finding("PROXY_IPV6", f"IPv6 backend {address} is not bracketed", host, str(path)))

def validate_telemetry(root: Path, host: str, findings: list[Finding]) -> None:
    path = rootfs(root, host, "/etc/telemetry/targets.yml")
    if not path.is_file():
        findings.append(Finding("TELEMETRY_MISSING", "telemetry target document is missing", host, str(path)))
        return
    try:
        data = read_yaml(path)
    except Exception as exc:
        findings.append(Finding("TELEMETRY_YAML", f"telemetry YAML cannot be parsed: {exc}", host, str(path)))
        return
    targets = data.get("targets", []) if isinstance(data, Mapping) else []
    if not isinstance(targets, list):
        findings.append(Finding("TELEMETRY_SHAPE", "targets must be a list", host, str(path)))
        return
    identities = set()
    for row in targets:
        if not isinstance(row, Mapping):
            findings.append(Finding("TELEMETRY_ROW", "target must be a mapping", host, str(path)))
            continue
        key = (str(row.get("host", "")), int(row.get("port", 0) or 0))
        if key in identities:
            findings.append(Finding("TELEMETRY_DUPLICATE", f"duplicate telemetry target {key}", host, str(path)))
        identities.add(key)
    if len(targets) < 3:
        findings.append(Finding("TELEMETRY_COVERAGE", "telemetry target set is unexpectedly small", host, str(path)))

def validate_policy(root: Path, host: str, findings: list[Finding]) -> None:
    path = rootfs(root, host, "/etc/fleet/policy.conf")
    if not path.is_file():
        findings.append(Finding("POLICY_MISSING", "policy file is missing", host, str(path)))
        return
    priorities = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 8 or parts[0] != "priority":
            findings.append(Finding("POLICY_SYNTAX", f"malformed policy line {number}", host, str(path)))
            continue
        try:
            priorities.append(int(parts[1]))
        except ValueError:
            findings.append(Finding("POLICY_PRIORITY", f"invalid priority line {number}", host, str(path)))
    if priorities != sorted(priorities):
        findings.append(Finding("POLICY_ORDER", "policy priorities are not numeric ascending", host, str(path)))
    if len(priorities) != len(set(priorities)):
        findings.append(Finding("POLICY_COLLISION", "policy priorities collide", host, str(path)))

def validate_secret_hygiene(root: Path, host: str, findings: list[Finding]) -> None:
    for relative in ("/etc/fleet/application.yml", "/etc/nginx/conf.d/fleet.conf", "/etc/telemetry/targets.yml"):
        path = rootfs(root, host, relative)
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").lower().splitlines():
            for needle in ("password:", "secret:", "token:"):
                if needle in line and "<redacted>" not in line and "secret_ref" not in line:
                    findings.append(Finding("SECRET_EXPOSED", f"sensitive material appears inline in {relative}", host, str(path)))

def validate_host(root: Path, host: str) -> dict[str, Any]:
    findings = []
    validate_identity(root, host, findings)
    validate_trust(root, host, findings)
    validate_application(root, host, findings)
    validate_proxy(root, host, findings)
    validate_telemetry(root, host, findings)
    validate_policy(root, host, findings)
    validate_secret_hygiene(root, host, findings)
    state = HostState(root, host).verify_materialized()
    if not state["ok"]:
        findings.append(Finding("STATE_DRIFT", "materialized files do not match state manifest", host))
    return {"host": host, "ok": not any(f.severity == "error" for f in findings), "findings": [f.to_dict() for f in findings], "state": state}

def validate_fleet(root: Path, hosts: list[str]) -> dict[str, Any]:
    rows = [validate_host(root, host) for host in hosts]
    codes = {}
    for row in rows:
        for finding in row["findings"]:
            codes[finding["code"]] = codes.get(finding["code"], 0) + 1
    return {"schema": "fleet-validation/v1", "ok": all(row["ok"] for row in rows), "hosts": rows, "finding_counts": dict(sorted(codes.items()))}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="runtime")
    parser.add_argument("--output", default="runtime/reports/fleet-validation.json")
    parser.add_argument("hosts", nargs="+")
    args = parser.parse_args()
    report = validate_fleet(Path(args.root), args.hosts)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "hosts": len(report["hosts"]), "findings": report["finding_counts"]}, sort_keys=True))
    return 0 if report["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
