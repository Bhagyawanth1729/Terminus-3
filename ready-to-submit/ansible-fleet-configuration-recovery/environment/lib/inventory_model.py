from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import ip_address, ip_network
from typing import Any, Iterable, Mapping, Sequence


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    protocol: str = "http"
    weight: int = 1
    zone: str = ""

    def normalized_host(self) -> str:
        try:
            return str(ip_address(self.host))
        except ValueError:
            return self.host.rstrip(".").lower()

    def authority(self) -> str:
        host = self.normalized_host()
        try:
            parsed = ip_address(host)
        except ValueError:
            return f"{host}:{self.port}"
        if parsed.version == 6:
            return f"[{host}]:{self.port}"
        return f"{host}:{self.port}"

    def identity(self) -> tuple[str, int, str, str]:
        return self.normalized_host(), self.port, self.protocol.lower(), self.zone


@dataclass(frozen=True)
class HostIdentity:
    name: str
    site: str
    roles: tuple[str, ...]
    address: str
    zone: str
    labels: Mapping[str, str] = field(default_factory=dict)

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def label(self, key: str, default: str = "") -> str:
        return str(self.labels.get(key, default))


@dataclass(frozen=True)
class ServiceBinding:
    service: str
    endpoint: Endpoint
    host: str
    site: str
    enabled: bool = True


@dataclass(frozen=True)
class SiteModel:
    name: str
    hosts: tuple[HostIdentity, ...]
    management_cidrs: tuple[str, ...]
    failure_domain: str

    def by_role(self, role: str) -> tuple[HostIdentity, ...]:
        return tuple(host for host in self.hosts if host.has_role(role))

    def host_names(self) -> tuple[str, ...]:
        return tuple(host.name for host in self.hosts)


@dataclass(frozen=True)
class FleetModel:
    sites: Mapping[str, SiteModel]
    services: Mapping[str, tuple[ServiceBinding, ...]]
    groups: Mapping[str, tuple[str, ...]]

    def hosts(self) -> tuple[HostIdentity, ...]:
        return tuple(host for site in self.sites.values() for host in site.hosts)

    def host_map(self) -> dict[str, HostIdentity]:
        return {host.name: host for host in self.hosts()}

    def site(self, name: str) -> SiteModel:
        if name not in self.sites:
            raise InventoryError(f"unknown site {name!r}")
        return self.sites[name]

    def service(self, name: str) -> tuple[ServiceBinding, ...]:
        return self.services.get(name, ())

    def group(self, name: str) -> tuple[str, ...]:
        return self.groups.get(name, ())


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InventoryError(f"{label} must be a mapping")
    return value


def _as_sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InventoryError(f"{label} must be a sequence")
    return value


def _site_from_groups(group_names: Iterable[str], sites: Sequence[str]) -> str:
    matches = [site for site in sites if site in set(group_names)]
    if len(matches) != 1:
        raise InventoryError(f"host must belong to exactly one site, found {matches}")
    return matches[0]


def _roles_from_groups(group_names: Iterable[str]) -> tuple[str, ...]:
    roles: list[str] = []
    names = set(group_names)
    if "application_nodes" in names:
        roles.append("application")
    if "proxy_nodes" in names:
        roles.append("proxy")
    if "database_nodes" in names:
        roles.append("database")
    if "telemetry_collectors" in names:
        roles.append("telemetry")
    return tuple(sorted(roles))


def normalize_endpoint(value: Any, *, default_port: int, default_zone: str) -> Endpoint:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise InventoryError("endpoint string cannot be empty")
        if text.startswith("["):
            closing = text.find("]")
            if closing < 0:
                raise InventoryError(f"invalid bracketed endpoint {text!r}")
            host = text[1:closing]
            suffix = text[closing + 1 :]
            port = default_port if not suffix else int(suffix.removeprefix(":"))
            return Endpoint(host=host, port=port, zone=default_zone)
        if text.count(":") == 1:
            host, raw_port = text.rsplit(":", 1)
            return Endpoint(host=host, port=int(raw_port), zone=default_zone)
        try:
            ip_address(text)
            return Endpoint(host=text, port=default_port, zone=default_zone)
        except ValueError as exc:
            raise InventoryError(f"ambiguous endpoint {text!r}") from exc
    mapping = _as_mapping(value, "endpoint")
    if "endpoint" in mapping:
        nested = _as_mapping(mapping["endpoint"], "endpoint.endpoint")
    else:
        nested = mapping
    host = str(nested.get("host", "")).strip()
    if not host:
        raise InventoryError("endpoint host is required")
    port = int(nested.get("port", default_port))
    if not 1 <= port <= 65535:
        raise InventoryError(f"endpoint port out of range: {port}")
    protocol = str(nested.get("protocol", "http")).strip().lower()
    weight = int(nested.get("weight", 1))
    zone = str(nested.get("zone", default_zone)).strip()
    if weight <= 0:
        raise InventoryError("endpoint weight must be positive")
    return Endpoint(host=host, port=port, protocol=protocol, weight=weight, zone=zone)


def validate_management_cidrs(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in values:
        network = ip_network(str(raw), strict=False)
        canonical = str(network)
        if canonical not in normalized:
            normalized.append(canonical)
    if not normalized:
        raise InventoryError("at least one management CIDR is required")
    return tuple(normalized)


def address_in_management_scope(address: str, cidrs: Sequence[str]) -> bool:
    parsed = ip_address(address)
    return any(parsed in ip_network(cidr, strict=False) for cidr in cidrs)


def build_host_identity(
    name: str,
    hostvars: Mapping[str, Any],
    *,
    known_sites: Sequence[str],
) -> HostIdentity:
    group_names = tuple(str(item) for item in hostvars.get("group_names", ()))
    site = _site_from_groups(group_names, known_sites)
    roles = _roles_from_groups(group_names)
    address = str(hostvars.get("ansible_host", "")).strip()
    if not address:
        raise InventoryError(f"host {name} has no ansible_host")
    zone = str(hostvars.get("fleet_zone", f"{site}-unknown"))
    labels_raw = hostvars.get("fleet_labels", {})
    labels_mapping = _as_mapping(labels_raw, f"{name}.fleet_labels")
    labels = {str(key): str(value) for key, value in labels_mapping.items()}
    return HostIdentity(
        name=name,
        site=site,
        roles=roles,
        address=address,
        zone=zone,
        labels=labels,
    )


def build_service_binding(
    host: HostIdentity,
    service: str,
    value: Any,
    *,
    default_port: int,
) -> ServiceBinding:
    endpoint = normalize_endpoint(value, default_port=default_port, default_zone=host.zone)
    return ServiceBinding(
        service=service,
        endpoint=endpoint,
        host=host.name,
        site=host.site,
        enabled=True,
    )


def _expand_group_children(
    group: str,
    raw_groups: Mapping[str, Any],
    *,
    stack: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if group in stack:
        raise InventoryError(f"group cycle detected: {' -> '.join((*stack, group))}")
    raw = raw_groups.get(group, {})
    mapping = _as_mapping(raw, f"group {group}")
    hosts = mapping.get("hosts", {})
    children = mapping.get("children", {})
    host_names = list(_as_mapping(hosts, f"{group}.hosts").keys())
    child_mapping = _as_mapping(children, f"{group}.children")
    for child in child_mapping:
        host_names.extend(_expand_group_children(str(child), raw_groups, stack=(*stack, group)))
    return tuple(dict.fromkeys(str(name) for name in host_names))


def derive_groups(raw_groups: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for group in raw_groups:
        result[str(group)] = _expand_group_children(str(group), raw_groups)
    return result


def backend_distribution(bindings: Sequence[ServiceBinding]) -> dict[str, dict[str, int]]:
    distribution: dict[str, dict[str, int]] = {}
    for binding in bindings:
        site_bucket = distribution.setdefault(binding.site, {})
        zone = binding.endpoint.zone or "unknown"
        site_bucket[zone] = site_bucket.get(zone, 0) + 1
    return distribution


def validate_backend_distribution(
    bindings: Sequence[ServiceBinding],
    *,
    minimum_sites: int,
    minimum_backends_per_site: int,
) -> None:
    distribution = backend_distribution(bindings)
    if len(distribution) < minimum_sites:
        raise InventoryError(
            f"backend service spans {len(distribution)} sites; require {minimum_sites}"
        )
    for site, zones in distribution.items():
        count = sum(zones.values())
        if count < minimum_backends_per_site:
            raise InventoryError(
                f"site {site} has {count} backends; require {minimum_backends_per_site}"
            )


def detect_endpoint_collisions(bindings: Sequence[ServiceBinding]) -> dict[tuple[str, int, str, str], list[str]]:
    owners: dict[tuple[str, int, str, str], list[str]] = {}
    for binding in bindings:
        owners.setdefault(binding.endpoint.identity(), []).append(binding.host)
    return {identity: hosts for identity, hosts in owners.items() if len(hosts) > 1}


def select_hosts(
    fleet: FleetModel,
    *,
    sites: Sequence[str] | None = None,
    roles: Sequence[str] | None = None,
    labels: Mapping[str, str] | None = None,
) -> tuple[HostIdentity, ...]:
    allowed_sites = set(sites or fleet.sites)
    required_roles = set(roles or ())
    required_labels = dict(labels or {})
    selected: list[HostIdentity] = []
    for host in fleet.hosts():
        if host.site not in allowed_sites:
            continue
        if required_roles and not required_roles.issubset(host.roles):
            continue
        if any(host.label(key) != value for key, value in required_labels.items()):
            continue
        selected.append(host)
    return tuple(sorted(selected, key=lambda item: (item.site, item.zone, item.name)))


def partition_by_site(hosts: Sequence[HostIdentity]) -> dict[str, tuple[HostIdentity, ...]]:
    buckets: dict[str, list[HostIdentity]] = {}
    for host in hosts:
        buckets.setdefault(host.site, []).append(host)
    return {
        site: tuple(sorted(values, key=lambda item: (item.zone, item.name)))
        for site, values in sorted(buckets.items())
    }


def service_hosts(fleet: FleetModel, service: str) -> tuple[HostIdentity, ...]:
    host_map = fleet.host_map()
    names = {binding.host for binding in fleet.service(service) if binding.enabled}
    return tuple(host_map[name] for name in sorted(names) if name in host_map)


def management_reachability_matrix(fleet: FleetModel) -> dict[str, dict[str, bool]]:
    matrix: dict[str, dict[str, bool]] = {}
    for site_name, site in fleet.sites.items():
        row: dict[str, bool] = {}
        for host in site.hosts:
            try:
                row[host.name] = address_in_management_scope(host.address, site.management_cidrs)
            except ValueError:
                row[host.name] = False
        matrix[site_name] = row
    return matrix


def assert_management_reachability(fleet: FleetModel) -> None:
    matrix = management_reachability_matrix(fleet)
    failures = [
        f"{site}/{host}"
        for site, row in matrix.items()
        for host, reachable in row.items()
        if not reachable
    ]
    if failures:
        raise InventoryError("hosts outside management CIDRs: " + ", ".join(sorted(failures)))


def stable_inventory_projection(fleet: FleetModel) -> dict[str, Any]:
    return {
        "sites": {
            site_name: {
                "failure_domain": site.failure_domain,
                "management_cidrs": list(site.management_cidrs),
                "hosts": [
                    {
                        "name": host.name,
                        "address": host.address,
                        "zone": host.zone,
                        "roles": list(host.roles),
                        "labels": dict(sorted(host.labels.items())),
                    }
                    for host in sorted(site.hosts, key=lambda item: item.name)
                ],
            }
            for site_name, site in sorted(fleet.sites.items())
        },
        "groups": {name: list(values) for name, values in sorted(fleet.groups.items())},
        "services": {
            service: [
                {
                    "host": binding.host,
                    "site": binding.site,
                    "authority": binding.endpoint.authority(),
                    "protocol": binding.endpoint.protocol,
                    "weight": binding.endpoint.weight,
                    "zone": binding.endpoint.zone,
                }
                for binding in sorted(
                    bindings,
                    key=lambda item: (
                        item.site,
                        item.endpoint.zone,
                        item.host,
                        item.endpoint.authority(),
                    ),
                )
            ]
            for service, bindings in sorted(fleet.services.items())
        },
    }


def compare_inventory(before: FleetModel, after: FleetModel) -> dict[str, Any]:
    before_hosts = before.host_map()
    after_hosts = after.host_map()
    added = sorted(set(after_hosts) - set(before_hosts))
    removed = sorted(set(before_hosts) - set(after_hosts))
    changed = sorted(
        name
        for name in set(before_hosts) & set(after_hosts)
        if before_hosts[name] != after_hosts[name]
    )
    service_changes: dict[str, dict[str, list[str]]] = {}
    service_names = set(before.services) | set(after.services)
    for service in sorted(service_names):
        left = {
            (binding.host, binding.endpoint.identity())
            for binding in before.service(service)
        }
        right = {
            (binding.host, binding.endpoint.identity())
            for binding in after.service(service)
        }
        if left == right:
            continue
        service_changes[service] = {
            "added": sorted(f"{host}:{identity}" for host, identity in right - left),
            "removed": sorted(f"{host}:{identity}" for host, identity in left - right),
        }
    return {
        "hosts_added": added,
        "hosts_removed": removed,
        "hosts_changed": changed,
        "service_changes": service_changes,
    }


def validate_fleet(fleet: FleetModel) -> None:
    host_map = fleet.host_map()
    if len(host_map) != len(fleet.hosts()):
        raise InventoryError("host names are not globally unique")
    for group, names in fleet.groups.items():
        missing = [name for name in names if name not in host_map]
        if missing:
            raise InventoryError(f"group {group} references missing hosts {missing}")
    for service, bindings in fleet.services.items():
        missing = [binding.host for binding in bindings if binding.host not in host_map]
        if missing:
            raise InventoryError(f"service {service} references missing hosts {missing}")
        collisions = detect_endpoint_collisions(bindings)
        if collisions:
            raise InventoryError(f"service {service} has endpoint collisions: {collisions}")
    assert_management_reachability(fleet)
