from __future__ import annotations
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from typing import Any, Iterable, Mapping, Sequence
import hashlib
import json

class FleetDataError(ValueError):
    pass

@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    weight: int = 1
    zone: str = ""
    protocol: str = "http"
    @property
    def family(self) -> int:
        try:
            return ip_address(self.host).version
        except ValueError:
            return 0
    def authority(self) -> str:
        if self.family == 6:
            return f"[{self.host}]:{self.port}"
        return f"{self.host}:{self.port}"
    def key(self) -> tuple:
        return (self.protocol, self.host.lower(), self.port, self.zone, self.weight)

def require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FleetDataError(f"{label} must be a mapping")
    return value

def require_sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise FleetDataError(f"{label} must be a sequence")
    return value

def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = {k: clone(v) for k, v in base.items()}
    for key, value in override.items():
        if key in out and isinstance(out[key], Mapping) and isinstance(value, Mapping):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = clone(value)
    return out

def clone(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: clone(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clone(v) for v in value]
    if isinstance(value, tuple):
        return tuple(clone(v) for v in value)
    return value

def split_host_port(text: str, default_port: int) -> tuple[str, int]:
    value = text.strip()
    if value.startswith("["):
        if "]:" in value:
            host, port = value[1:].split("]:", 1)
            return host, int(port)
        return value.strip("[]"), default_port
    if value.count(":") == 1:
        host, maybe_port = value.rsplit(":", 1)
        if maybe_port.isdigit():
            return host, int(maybe_port)
    if value.count(":") > 1:
        return value, default_port
    return value, default_port

def normalized_endpoint(value: Any, default_port: int = 8080) -> dict[str, Any]:
    if isinstance(value, str):
        host, port = split_host_port(value, default_port)
        record = {"host": host, "port": port, "weight": 1, "zone": "", "protocol": "http"}
    elif isinstance(value, Mapping):
        record = dict(value)
        record.setdefault("port", default_port)
        record.setdefault("weight", 1)
        record.setdefault("zone", "")
        record.setdefault("protocol", "http")
    else:
        raise FleetDataError("endpoint must be a mapping or string")
    host = str(record.get("host", "")).strip()
    if not host:
        raise FleetDataError("endpoint host is required")
    try:
        port = int(record["port"])
        weight = int(record["weight"])
    except (TypeError, ValueError) as exc:
        raise FleetDataError("endpoint port and weight must be integers") from exc
    if not 1 <= port <= 65535:
        raise FleetDataError("endpoint port outside 1..65535")
    if not 1 <= weight <= 100:
        raise FleetDataError("endpoint weight outside 1..100")
    protocol = str(record["protocol"]).lower()
    if protocol not in {"http", "https", "grpc", "tcp"}:
        raise FleetDataError(f"unsupported endpoint protocol {protocol}")
    return {"host": host, "port": port, "weight": weight, "zone": str(record["zone"]), "protocol": protocol}

def endpoint_authority(value: Any, default_port: int = 8080) -> str:
    row = normalized_endpoint(value, default_port)
    try:
        family = ip_address(row["host"]).version
    except ValueError:
        family = 0
    host = f'[{row["host"]}]' if family == 6 else row["host"]
    return f'{host}:{row["port"]}'

def normalize_backend_set(values: Iterable[Any], default_port: int = 8080) -> list[dict[str, Any]]:
    normalized = [normalized_endpoint(v, default_port) for v in values]
    unique = {}
    for row in normalized:
        key = (row["protocol"], row["host"].lower(), row["port"], row["zone"], row["weight"])
        unique[key] = row
    return [unique[key] for key in sorted(unique)]

def group_backends_by_zone(values: Iterable[Any], default_port: int = 8080) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for row in normalize_backend_set(values, default_port):
        out.setdefault(row["zone"] or "unassigned", []).append(row)
    return out

def validate_backend_quorum(values: Iterable[Any], minimum: int, zones: int) -> dict[str, Any]:
    rows = normalize_backend_set(values)
    zone_names = {r["zone"] for r in rows if r["zone"]}
    return {"count": len(rows), "zones": sorted(zone_names), "healthy": len(rows) >= minimum and len(zone_names) >= zones}

def normalize_cidr(value: str) -> str:
    return str(ip_network(str(value), strict=False))

def normalize_cidrs(values: Iterable[str]) -> list[str]:
    return sorted({normalize_cidr(v) for v in values}, key=lambda x: (ip_network(x).version, int(ip_network(x).network_address), ip_network(x).prefixlen))

def network_contains(parent: str, child: str) -> bool:
    return ip_network(child, strict=False).subnet_of(ip_network(parent, strict=False))

def policy_priority(value: Any) -> int:
    try:
        priority = int(value)
    except (TypeError, ValueError) as exc:
        raise FleetDataError(f"invalid policy priority {value!r}") from exc
    if not 1 <= priority <= 65535:
        raise FleetDataError("policy priority outside 1..65535")
    return priority

def normalize_policy_rules(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for raw in values:
        row = dict(require_mapping(raw, "policy rule"))
        row["priority"] = policy_priority(row.get("priority"))
        row["action"] = str(row.get("action", "deny")).lower()
        row["source"] = normalize_cidr(str(row.get("source", "0.0.0.0/0")))
        row["destination"] = normalize_cidr(str(row.get("destination", "0.0.0.0/0")))
        row["protocol"] = str(row.get("protocol", "any")).lower()
        row["port"] = int(row.get("port", 0))
        key = (row["priority"], row["source"], row["destination"], row["protocol"], row["port"], row["action"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return sorted(out, key=lambda r: (r["priority"], r["source"], r["destination"], r["protocol"], r["port"]))

def validate_priority_collisions(values: Iterable[Mapping[str, Any]]) -> list[int]:
    counts = {}
    for row in values:
        p = policy_priority(row.get("priority"))
        counts[p] = counts.get(p, 0) + 1
    return sorted(p for p, count in counts.items() if count > 1)

def service_catalog_index(catalog: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    services = require_sequence(catalog.get("services", []), "services")
    index = {}
    for raw in services:
        row = dict(require_mapping(raw, "service"))
        name = str(row.get("name", "")).strip()
        if not name:
            raise FleetDataError("service name is required")
        if name in index:
            raise FleetDataError(f"duplicate service {name}")
        row["port"] = int(row.get("port", 8080))
        row["replicas"] = int(row.get("replicas", 1))
        row["dependencies"] = sorted(set(str(v) for v in row.get("dependencies", [])))
        index[name] = row
    return index

def dependency_order(catalog: Mapping[str, Any]) -> list[str]:
    index = service_catalog_index(catalog)
    pending = {name: set(row["dependencies"]) for name, row in index.items()}
    order = []
    while pending:
        ready = sorted(name for name, deps in pending.items() if not deps)
        if not ready:
            cycle = ", ".join(sorted(pending))
            raise FleetDataError(f"service dependency cycle: {cycle}")
        for name in ready:
            order.append(name)
            pending.pop(name)
        for deps in pending.values():
            deps.difference_update(ready)
    return order

def select_services(catalog: Mapping[str, Any], site: str, environment: str) -> list[dict[str, Any]]:
    index = service_catalog_index(catalog)
    selected = []
    for name in dependency_order(catalog):
        row = index[name]
        allowed_sites = set(row.get("sites", ["all"]))
        allowed_env = set(row.get("environments", ["all"]))
        if "all" not in allowed_sites and site not in allowed_sites:
            continue
        if "all" not in allowed_env and environment not in allowed_env:
            continue
        selected.append(row)
    return selected

def build_backend_graph(hostvars: Mapping[str, Any], groups: Mapping[str, Any], service: str) -> list[dict[str, Any]]:
    members = list(groups.get("application_nodes", []))
    rows = []
    for host in members:
        hv = require_mapping(hostvars.get(host, {}), f"hostvars[{host}]")
        services = require_mapping(hv.get("fleet_services", {}), f"{host}.fleet_services")
        item = services.get(service)
        if item is None:
            continue
        endpoint = item.get("endpoint", item) if isinstance(item, Mapping) else item
        row = normalized_endpoint(endpoint)
        row["inventory_host"] = host
        rows.append(row)
    return normalize_backend_set(rows)

def telemetry_targets(hostvars: Mapping[str, Any], groups: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for group_name in ("application_nodes", "proxy_nodes", "database_nodes"):
        for host in groups.get(group_name, []):
            hv = require_mapping(hostvars.get(host, {}), f"hostvars[{host}]")
            address = hv.get("telemetry_address", hv.get("ansible_host", host))
            port = int(hv.get("telemetry_port", 9100))
            rows.append({"host": str(address), "port": port, "group": group_name, "inventory_host": host})
    unique = {}
    for row in rows:
        unique[(row["host"], row["port"])] = row
    return [unique[k] for k in sorted(unique)]

def merge_site_settings(global_settings: Mapping[str, Any], site_settings: Mapping[str, Any], host_settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    merged = deep_merge(global_settings, site_settings)
    if host_settings:
        merged = deep_merge(merged, host_settings)
    return merged

def redact_mapping(value: Mapping[str, Any], sensitive_words: Iterable[str] | None = None) -> dict[str, Any]:
    words = tuple(sensitive_words or ("password", "secret", "token", "private_key", "credential"))
    out = {}
    for key, val in value.items():
        if any(word in str(key).lower() for word in words):
            out[key] = "<redacted>"
        elif isinstance(val, Mapping):
            out[key] = redact_mapping(val, words)
        elif isinstance(val, list):
            out[key] = [redact_mapping(v, words) if isinstance(v, Mapping) else v for v in val]
        else:
            out[key] = val
    return out

def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def stable_digest(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode()).hexdigest()

def render_manifest(host: str, components: Mapping[str, Any]) -> dict[str, Any]:
    entries = {}
    for name, value in sorted(components.items()):
        entries[name] = {"sha256": stable_digest(value), "kind": type(value).__name__}
    return {"schema": "fleet-render-manifest/v1", "host": host, "entries": entries, "digest": stable_digest(entries)}

def weighted_capacity(values: Iterable[Any]) -> int:
    return sum(normalized_endpoint(v)["weight"] for v in values)

def zone_capacity(values: Iterable[Any]) -> dict[str, int]:
    out = {}
    for row in normalize_backend_set(values):
        zone = row["zone"] or "unassigned"
        out[zone] = out.get(zone, 0) + row["weight"]
    return dict(sorted(out.items()))

def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "yes", "true", "on", "enabled"}:
        return True
    if text in {"0", "no", "false", "off", "disabled", ""}:
        return False
    raise FleetDataError(f"cannot convert {value!r} to bool")

def clamp(value: Any, minimum: int, maximum: int) -> int:
    number = int(value)
    return max(minimum, min(maximum, number))

def rollout_batches(hosts: Iterable[str], canaries: Iterable[str], batch_size: int) -> list[list[str]]:
    canary_set = set(canaries)
    remaining = [h for h in sorted(set(hosts)) if h not in canary_set]
    batches = []
    first = sorted(canary_set)
    if first:
        batches.append(first)
    width = max(1, int(batch_size))
    for start in range(0, len(remaining), width):
        batches.append(remaining[start:start + width])
    return batches

def trust_bundle_order(certificates: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for raw in certificates:
        row = dict(raw)
        row["priority"] = int(row.get("priority", 100))
        row["name"] = str(row.get("name", ""))
        row["pem"] = str(row.get("pem", "")).strip() + "\n"
        rows.append(row)
    return sorted(rows, key=lambda r: (r["priority"], r["name"]))

def validate_catalog_dependencies(catalog: Mapping[str, Any]) -> list[str]:
    index = service_catalog_index(catalog)
    missing = []
    for name, row in index.items():
        for dep in row["dependencies"]:
            if dep not in index:
                missing.append(f"{name}->{dep}")
    return sorted(missing)

def build_environment_projection(catalog: Mapping[str, Any], settings: Mapping[str, Any], site: str, environment: str) -> dict[str, Any]:
    services = select_services(catalog, site, environment)
    return {"site": site, "environment": environment, "service_count": len(services), "services": [{"name": r["name"], "port": r["port"], "replicas": r["replicas"], "owner": r.get("owner", "")} for r in services], "settings": redact_mapping(settings)}

class FilterModule:
    def filters(self):
        return {
            "deep_merge": deep_merge,
            "normalized_endpoint": normalized_endpoint,
            "endpoint_authority": endpoint_authority,
            "normalize_backend_set": normalize_backend_set,
            "group_backends_by_zone": group_backends_by_zone,
            "validate_backend_quorum": validate_backend_quorum,
            "normalize_cidr": normalize_cidr,
            "normalize_cidrs": normalize_cidrs,
            "network_contains": network_contains,
            "policy_priority": policy_priority,
            "normalize_policy_rules": normalize_policy_rules,
            "validate_priority_collisions": validate_priority_collisions,
            "dependency_order": dependency_order,
            "select_services": select_services,
            "build_backend_graph": build_backend_graph,
            "telemetry_targets": telemetry_targets,
            "merge_site_settings": merge_site_settings,
            "redact_mapping": redact_mapping,
            "stable_digest": stable_digest,
            "render_manifest": render_manifest,
            "weighted_capacity": weighted_capacity,
            "zone_capacity": zone_capacity,
            "safe_bool": safe_bool,
            "clamp": clamp,
            "rollout_batches": rollout_batches,
            "trust_bundle_order": trust_bundle_order,
            "validate_catalog_dependencies": validate_catalog_dependencies,
            "build_environment_projection": build_environment_projection,
        }
