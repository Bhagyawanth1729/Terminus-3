from __future__ import annotations
from dataclasses import dataclass, field
from ipaddress import ip_network
from pathlib import Path
from typing import Any, Iterable, Mapping
import argparse
import json
import yaml

class PolicyError(ValueError):
    pass

@dataclass(frozen=True)
class Flow:
    source: str
    destination: str
    protocol: str
    port: int
    site: str
    owner: str

@dataclass(frozen=True)
class Rule:
    rule_id: str
    priority: int
    source: str
    destination: str
    protocol: str
    port: int
    action: str
    site: str
    owner: str
    change_window: str
    description: str = ""
    def key(self) -> tuple[Any, ...]:
        return (self.priority, self.source, self.destination, self.protocol, self.port, self.action)
    def matches(self, flow: Flow) -> bool:
        if self.site not in {"all", flow.site}:
            return False
        if self.protocol not in {"any", flow.protocol}:
            return False
        if self.port not in {0, flow.port}:
            return False
        source_ok = ip_network(flow.source, strict=False).subnet_of(ip_network(self.source, strict=False))
        destination_ok = ip_network(flow.destination, strict=False).subnet_of(ip_network(self.destination, strict=False))
        return source_ok and destination_ok

@dataclass
class Decision:
    allowed: bool
    rule_id: str | None
    priority: int | None
    reason: str
    evaluated: int
    candidates: list[str] = field(default_factory=list)

@dataclass
class PolicySet:
    rules: list[Rule]
    default_action: str = "deny"
    def ordered(self) -> list[Rule]:
        return sorted(self.rules, key=lambda row: (row.priority, row.rule_id))
    def collisions(self) -> dict[int, list[str]]:
        groups: dict[int, list[str]] = {}
        for rule in self.rules:
            groups.setdefault(rule.priority, []).append(rule.rule_id)
        return {priority: sorted(ids) for priority, ids in groups.items() if len(ids) > 1}
    def duplicates(self) -> list[list[str]]:
        groups: dict[tuple[Any, ...], list[str]] = {}
        for rule in self.rules:
            groups.setdefault(rule.key(), []).append(rule.rule_id)
        return [sorted(ids) for ids in groups.values() if len(ids) > 1]
    def decide(self, flow: Flow) -> Decision:
        candidates = []
        evaluated = 0
        for rule in self.ordered():
            evaluated += 1
            if not rule.matches(flow):
                continue
            candidates.append(rule.rule_id)
            return Decision(rule.action == "allow", rule.rule_id, rule.priority, f"matched {rule.rule_id}", evaluated, candidates)
        return Decision(self.default_action == "allow", None, None, f"default {self.default_action}", evaluated, candidates)

def integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{label} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise PolicyError(f"{label} outside {minimum}..{maximum}")
    return result

def normalized_network(value: Any, label: str) -> str:
    try:
        return str(ip_network(str(value), strict=False))
    except ValueError as exc:
        raise PolicyError(f"{label} is not a valid network: {value!r}") from exc

def parse_rule(raw: Mapping[str, Any]) -> Rule:
    rule_id = str(raw.get("id", "")).strip()
    if not rule_id:
        raise PolicyError("policy rule id is required")
    action = str(raw.get("action", "deny")).lower()
    if action not in {"allow", "deny"}:
        raise PolicyError(f"rule {rule_id} has invalid action {action}")
    protocol = str(raw.get("protocol", "any")).lower()
    if protocol not in {"any", "tcp", "udp"}:
        raise PolicyError(f"rule {rule_id} has invalid protocol {protocol}")
    return Rule(
        rule_id=rule_id,
        priority=integer(raw.get("priority"), f"{rule_id}.priority", 1, 65535),
        source=normalized_network(raw.get("source", "0.0.0.0/0"), f"{rule_id}.source"),
        destination=normalized_network(raw.get("destination", "0.0.0.0/0"), f"{rule_id}.destination"),
        protocol=protocol,
        port=integer(raw.get("port", 0), f"{rule_id}.port", 0, 65535),
        action=action,
        site=str(raw.get("site", "all")),
        owner=str(raw.get("owner", "unowned")),
        change_window=str(raw.get("change_window", "always")),
        description=str(raw.get("description", "")),
    )

def parse_rules(values: Iterable[Mapping[str, Any]], default_action: str = "deny") -> PolicySet:
    rules = [parse_rule(raw) for raw in values]
    ids = [rule.rule_id for rule in rules]
    if len(ids) != len(set(ids)):
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        raise PolicyError(f"duplicate rule ids: {', '.join(duplicates)}")
    return PolicySet(rules, default_action)

def load_policy(path: Path) -> PolicySet:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise PolicyError("policy catalog must be a mapping")
    values = data.get("rules", [])
    if not isinstance(values, list):
        raise PolicyError("policy catalog rules must be a list")
    return parse_rules(values, str(data.get("default_action", "deny")))

def render_rule(rule: Rule) -> str:
    return " ".join([
        "priority", str(rule.priority),
        "source", rule.source,
        "destination", rule.destination,
        "protocol", rule.protocol,
        "port", str(rule.port),
        "action", rule.action,
        "id", rule.rule_id,
        "owner", rule.owner,
    ])

def render_policy(policy: PolicySet, site: str) -> str:
    selected = [rule for rule in policy.ordered() if rule.site in {"all", site}]
    lines = [render_rule(rule) for rule in selected]
    return "\n".join(lines) + ("\n" if lines else "")

def coverage_by_site(policy: PolicySet) -> dict[str, dict[str, int]]:
    output: dict[str, dict[str, int]] = {}
    for rule in policy.rules:
        row = output.setdefault(rule.site, {"allow": 0, "deny": 0, "tcp": 0, "udp": 0, "any": 0})
        row[rule.action] += 1
        row[rule.protocol] += 1
    return dict(sorted(output.items()))

def coverage_by_owner(policy: PolicySet) -> dict[str, int]:
    output: dict[str, int] = {}
    for rule in policy.rules:
        output[rule.owner] = output.get(rule.owner, 0) + 1
    return dict(sorted(output.items()))

def management_flows() -> list[Flow]:
    return [
        Flow("10.40.1.0/24", "10.40.0.0/16", "tcp", 22, "blr", "platform"),
        Flow("10.50.1.0/24", "10.50.0.0/16", "tcp", 22, "maa", "platform"),
        Flow("10.60.1.0/24", "10.60.0.0/16", "tcp", 22, "hyd", "platform"),
        Flow("10.40.5.0/24", "10.40.10.0/24", "tcp", 9100, "blr", "observability"),
        Flow("10.50.5.0/24", "10.50.10.0/24", "tcp", 9100, "maa", "observability"),
        Flow("10.60.5.0/24", "10.60.10.0/24", "tcp", 9100, "hyd", "observability"),
    ]

def validate_management(policy: PolicySet) -> list[dict[str, Any]]:
    failures = []
    for flow in management_flows():
        decision = policy.decide(flow)
        if not decision.allowed:
            failures.append({"flow": flow.__dict__, "decision": decision.__dict__})
    return failures

def validate_change_windows(policy: PolicySet, allowed: set[str] | None = None) -> list[str]:
    values = allowed or {"always", "business-hours", "maintenance", "emergency"}
    return sorted(rule.rule_id for rule in policy.rules if rule.change_window not in values)

def validate_ownership(policy: PolicySet) -> list[str]:
    return sorted(rule.rule_id for rule in policy.rules if not rule.owner or rule.owner in {"unowned", "unknown"})

def validate_policy_set(policy: PolicySet) -> dict[str, Any]:
    collisions = policy.collisions()
    duplicates = policy.duplicates()
    windows = validate_change_windows(policy)
    ownership = validate_ownership(policy)
    management = validate_management(policy)
    return {
        "ok": not collisions and not duplicates and not windows and not ownership and not management,
        "rule_count": len(policy.rules),
        "priority_collisions": collisions,
        "semantic_duplicates": duplicates,
        "invalid_change_windows": windows,
        "unowned_rules": ownership,
        "management_failures": management,
        "coverage_by_site": coverage_by_site(policy),
        "coverage_by_owner": coverage_by_owner(policy),
    }

def diff_policy(before: PolicySet, after: PolicySet) -> dict[str, Any]:
    left = {rule.rule_id: rule for rule in before.rules}
    right = {rule.rule_id: rule for rule in after.rules}
    created = sorted(set(right) - set(left))
    deleted = sorted(set(left) - set(right))
    changed = sorted(rule_id for rule_id in set(left) & set(right) if left[rule_id] != right[rule_id])
    unchanged = sorted(rule_id for rule_id in set(left) & set(right) if left[rule_id] == right[rule_id])
    return {"created": created, "deleted": deleted, "changed": changed, "unchanged": unchanged}

def risky_changes(before: PolicySet, after: PolicySet) -> list[dict[str, Any]]:
    output = []
    before_map = {rule.rule_id: rule for rule in before.rules}
    after_map = {rule.rule_id: rule for rule in after.rules}
    for rule_id in sorted(set(before_map) | set(after_map)):
        old = before_map.get(rule_id)
        new = after_map.get(rule_id)
        if old and not new and old.action == "allow":
            output.append({"rule_id": rule_id, "risk": "allow-rule-deletion", "before": old.__dict__, "after": None})
        elif old and new and old.action == "allow" and new.action == "deny":
            output.append({"rule_id": rule_id, "risk": "allow-to-deny", "before": old.__dict__, "after": new.__dict__})
        elif not old and new and new.action == "allow" and new.source in {"0.0.0.0/0", "::/0"}:
            output.append({"rule_id": rule_id, "risk": "broad-new-allow", "before": None, "after": new.__dict__})
    return output

def policy_report(path: Path, site: str | None = None) -> dict[str, Any]:
    policy = load_policy(path)
    report = validate_policy_set(policy)
    if site:
        report["rendered"] = render_policy(policy, site)
    return report

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog")
    parser.add_argument("--site")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = policy_report(Path(args.catalog), args.site)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
