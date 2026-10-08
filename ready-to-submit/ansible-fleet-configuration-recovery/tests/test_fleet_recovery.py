from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

TASK = Path(__file__).resolve().parents[1]
ENV = TASK / "environment"
INVENTORY = ENV / "inventory" / "hosts.yml"
SITE = ENV / "playbooks" / "site.yml"
VALIDATE = ENV / "playbooks" / "validate.yml"
VAULT = ENV / "inventory" / "group_vars" / "prod" / "vault.yml"
WRAPPER = ENV / "bin" / "fleet-ansible"


def run(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(args, cwd=TASK, text=True, capture_output=True, env=merged)


def loaded_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def role_names() -> list[str]:
    doc = loaded_yaml(SITE)
    names: list[str] = []
    for play in doc:
        for role in play.get("roles", []) or []:
            names.append(role if isinstance(role, str) else role.get("role", ""))
    return names


def play_role_positions() -> dict[str, int]:
    return {name: index for index, name in enumerate(role_names())}


def durable_ansible_major() -> int:
    dockerfile = (ENV / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"ansible==([0-9]+)", dockerfile)
    assert match, "durable controller image must pin an ansible distribution"
    return int(match.group(1))


def project_ansible_cfg() -> Path:
    return ENV / "ansible.cfg"


@pytest.fixture(scope="module")
def converged_execution(tmp_path_factory):
    runtime = tmp_path_factory.mktemp("fleet-runtime")
    command = [
        str(WRAPPER),
        str(SITE),
        "-e",
        f"fleet_runtime_root={runtime}",
    ]
    first = run(command)
    assert first.returncode == 0, first.stdout + first.stderr
    second = run(command)
    assert second.returncode == 0, second.stdout + second.stderr
    return runtime, first, second


def test_f2p_controller_runtime_is_supported_major():
    assert durable_ansible_major() >= 12


def test_f2p_controller_config_init_capability_exists():
    cfg = project_ansible_cfg()
    assert cfg.is_file(), "project ansible.cfg must exist after controller config init"
    text = cfg.read_text(encoding="utf-8")
    assert "[defaults]" in text
    # ansible-config init --disabled emits a broad commented template retained by repair
    assert text.count("\n") >= 40


def test_f2p_controller_project_config_is_selected():
    cfg = project_ansible_cfg()
    assert cfg.is_file(), "project ansible.cfg must be selected for fleet automation"
    text = cfg.read_text(encoding="utf-8")
    assert "roles_path" in text
    assert "inventory" in text


def test_f2p_controller_durable_container_version_is_current():
    dockerfile = (ENV / "Dockerfile").read_text(encoding="utf-8")
    assert "ansible==2.9.27" not in dockerfile
    match = re.search(r"ansible==([0-9]+)", dockerfile)
    assert match and int(match.group(1)) >= 12


def test_f2p_discovery_project_roles_path_is_active():
    cfg = project_ansible_cfg().read_text(encoding="utf-8")
    assert "roles_path" in cfg
    assert "roles" in cfg
    assert "./environment/roles" in cfg or "./roles" in cfg or str(ENV / "roles") in cfg


def test_f2p_discovery_site_roles_resolve_locally():
    names = role_names()
    assert names
    missing = [name for name in names if not (ENV / "roles" / name).is_dir()]
    assert not missing, missing


def test_f2p_discovery_site_syntax_check_passes():
    result = run([str(WRAPPER), str(SITE), "--syntax-check"])
    assert result.returncode == 0, result.stdout + result.stderr


def test_f2p_secret_vault_is_encrypted_at_rest():
    first = VAULT.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("$ANSIBLE_VAULT;")


def test_f2p_secret_plaintext_markers_are_absent():
    text = VAULT.read_text(encoding="utf-8")
    for marker in (
        "Prod-Checkout-Temporary-Password",
        "prod-signing-token-placeholder",
        "proxy-shared-secret-placeholder",
        "telemetry-token-placeholder",
    ):
        assert marker not in text


def test_f2p_secret_vault_can_be_loaded_noninteractively():
    result = run(["ansible-vault", "view", str(VAULT)])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "database_password" in result.stdout


def test_f2p_orchestration_trust_precedes_application_release():
    positions = play_role_positions()
    assert positions["trust_bundle"] < positions["application_release"]


def test_f2p_orchestration_proxy_role_is_not_swapped_or_missing():
    names = role_names()
    assert "edge_proxy" in names
    assert "edge_proxy_config" not in names
    edge_play = next(play for play in loaded_yaml(SITE) if play.get("hosts") == "proxy_nodes")
    assert edge_play.get("roles") == ["edge_proxy"]


def test_f2p_orchestration_telemetry_executes_for_fleet():
    play = next(play for play in loaded_yaml(SITE) if "telemetry" in str(play.get("name", "")).lower())
    assert play.get("hosts") == "all"
    assert play.get("roles") == ["telemetry_agent"]


def test_f2p_orchestration_application_is_scoped_to_application_nodes():
    play = next(play for play in loaded_yaml(SITE) if "application tier" in str(play.get("name", "")).lower())
    assert play.get("hosts") == "application_nodes"
    assert play.get("roles") == ["application_release"]


def test_f2p_syntax_common_baseline_has_single_action_per_task():
    tasks = loaded_yaml(ENV / "roles" / "common_baseline" / "tasks" / "main.yml")
    action_keys = {"file", "copy", "package", "template", "command", "shell", "service", "systemd"}
    for task in tasks:
        assert len(action_keys.intersection(task)) <= 1, task


def test_f2p_syntax_validate_playbook_loop_control_is_well_formed():
    doc = loaded_yaml(VALIDATE)
    for task in doc[0]["tasks"]:
        if "loop_control" in task:
            assert isinstance(task["loop_control"], dict)
            assert "label" in task["loop_control"]
    result = run([str(WRAPPER), str(VALIDATE), "--syntax-check"])
    assert result.returncode == 0, result.stdout + result.stderr


def test_f2p_schema_copy_module_has_no_directory_mode_parameter():
    telemetry = loaded_yaml(ENV / "roles" / "telemetry_agent" / "tasks" / "main.yml")
    for task in telemetry:
        if "copy" in task:
            assert "directory_mode" not in task["copy"]


def test_f2p_jinja_hyd_dependencies_remain_structured():
    all_vars = loaded_yaml(ENV / "inventory" / "group_vars" / "all.yml")
    hyd = all_vars["fleet_site_overrides"]["hyd"]["application"]["dependencies"]
    assert isinstance(hyd, dict)
    assert int(hyd["timeout_seconds"]) == 4
    assert isinstance(hyd["tls"], dict)


def test_f2p_jinja_proxy_template_handles_all_endpoint_shapes():
    text = (ENV / "roles" / "edge_proxy" / "templates" / "upstreams.conf.j2").read_text(encoding="utf-8")
    assert "raw is string" in text
    assert "raw.endpoint if raw.endpoint is defined else raw" in text
    assert "rendered_host" in text


def test_f2p_jinja_proxy_template_brackets_ipv6_conditionally():
    text = (ENV / "roles" / "edge_proxy" / "templates" / "upstreams.conf.j2").read_text(encoding="utf-8")
    assert "'[' ~ raw_host ~ ']' if ':' in raw_host else raw_host" in text


def test_f2p_jinja_telemetry_missing_optional_group_is_safe():
    text = (ENV / "roles" / "telemetry_agent" / "templates" / "targets.yml.j2").read_text(encoding="utf-8")
    assert "groups.get('telemetry_collectors', [])" in text


def test_f2p_jinja_policy_priorities_are_rendered_numeric():
    text = (ENV / "roles" / "host_policy" / "templates" / "policy.conf.j2").read_text(encoding="utf-8")
    assert "rule.priority | int" in text
    assert "rule.port | int" in text


def test_f2p_jinja_application_dependency_output_is_a_list():
    text = (ENV / "roles" / "application_release" / "templates" / "application.yml.j2").read_text(encoding="utf-8")
    assert "dependencies:\n  - name:" in text
    assert "secret_ref:" in text
    assert "database_password:" not in text


def test_f2p_runtime_full_site_run_converges(converged_execution):
    runtime, first, _ = converged_execution
    assert runtime.is_dir()
    assert "failed=0" in first.stdout
    app = runtime / "rootfs" / "blr-app-01" / "etc" / "fleet" / "application.yml"
    assert app.is_file()
    proxy = (runtime / "rootfs" / "blr-proxy-01" / "etc" / "nginx" / "conf.d" / "fleet.conf").read_text(encoding="utf-8")
    assert "[2001:db8:40::11]:8080" in proxy
    assert "10.40.10.12:8080" in proxy


def test_f2p_runtime_second_run_is_idempotent(converged_execution):
    _, _, second = converged_execution
    changed = [int(value) for value in re.findall(r"changed=(\d+)", second.stdout)]
    assert changed and max(changed) == 0, second.stdout


def test_f2p_repair_preserves_sites_while_fixing_hyd_override():
    inventory = loaded_yaml(INVENTORY)
    children = inventory["all"]["children"]
    assert {"blr", "maa", "hyd"}.issubset(children)
    all_vars = loaded_yaml(ENV / "inventory" / "group_vars" / "all.yml")
    assert isinstance(all_vars["fleet_site_overrides"]["hyd"]["application"]["dependencies"], dict)


def test_f2p_repair_preserves_evidence_while_vaulting_secret():
    required = [
        ENV / "runtime" / "logs" / "incident-bootstrap.log",
        ENV / "runtime" / "logs" / "incident-playbook.log",
        ENV / "runtime" / "reports" / "incident-handoff.json",
        ENV / "runtime" / "evidence" / "config-selection.txt",
    ]
    assert all(path.is_file() and path.stat().st_size > 80 for path in required)
    assert VAULT.read_text(encoding="utf-8").startswith("$ANSIBLE_VAULT;")


def test_p2p_service_catalog_retains_production_breadth():
    catalog = loaded_yaml(ENV / "data" / "service-catalog.yml")
    services = catalog.get("services", catalog)
    assert len(services) >= 25


def test_p2p_policy_catalog_retains_sixty_owned_rules():
    rules = loaded_yaml(ENV / "data" / "policy-catalog.yml")["rules"]
    assert len(rules) == 60
    assert all(rule.get("owner") for rule in rules)


def test_p2p_inventory_retains_ipv4_and_ipv6_endpoints():
    text = INVENTORY.read_text(encoding="utf-8")
    assert "10.40.10.11" in text
    assert "2001:db8:40::11" in text
    assert "2001:db8:50::11" in text


def test_p2p_operator_logs_retain_sequential_failure_evidence():
    text = (ENV / "runtime" / "logs" / "incident-playbook.log").read_text(encoding="utf-8")
    assert "conflicting action statements" in text
    assert "fleet_vault" in text
    assert "telemetry_collectors" in text
    assert "directory_mode" in text


def test_p2p_official_helper_sources_are_upstream_ansible_only():
    lines = [line.strip() for line in (ENV / "docs" / "official-ansible-sources.txt").read_text(encoding="utf-8").splitlines()]
    urls = [line for line in lines if line.startswith("https://")]
    assert len(urls) >= 10
    assert all("docs.ansible.com" in url for url in urls)


def test_p2p_state_and_rollout_engines_remain_present():
    for name in ("state_engine.py", "inventory_model.py", "rollout_planner.py", "policy_engine.py", "fleet_validator.py"):
        path = ENV / "lib" / name
        assert path.is_file()
        assert len(path.read_text(encoding="utf-8").splitlines()) >= 150
