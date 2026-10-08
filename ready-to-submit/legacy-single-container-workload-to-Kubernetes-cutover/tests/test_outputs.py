"""Behavioural verification of the Kubernetes cutover manifests.

Collects agent YAML under /app/k8s and checks inventory-aligned split,
storage, availability, security, proxy/observability, and cross-object chains.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

MANIFEST_DIR = Path("/app/k8s")
INVENTORY_PATH = Path("/tests/fixtures/process-inventory.json")


def _documents(path: Path) -> list[dict]:
    docs: list[dict] = []
    text = path.read_text(encoding="utf-8")
    for doc in yaml.safe_load_all(text):
        if isinstance(doc, dict) and doc.get("kind"):
            docs.append(doc)
    return docs


@pytest.fixture(scope="session")
def inventory() -> dict:
    """Sealed process inventory used as the verifier contract."""
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def objects() -> list[dict]:
    """All Kubernetes objects parsed from /app/k8s."""
    assert MANIFEST_DIR.is_dir(), f"missing artifact directory {MANIFEST_DIR}"
    files = sorted(MANIFEST_DIR.rglob("*.yaml")) + sorted(MANIFEST_DIR.rglob("*.yml"))
    assert files, "no YAML manifests under /app/k8s"
    docs: list[dict] = []
    for path in files:
        docs.extend(_documents(path))
    assert docs, "no Kubernetes objects parsed from /app/k8s"
    return docs


@pytest.fixture(scope="session")
def by_kind(objects: list[dict]) -> dict[str, list[dict]]:
    """Kubernetes objects grouped by kind."""
    out: dict[str, list[dict]] = {}
    for obj in objects:
        out.setdefault(obj["kind"], []).append(obj)
    return out


def _containers(dep: dict) -> list[dict]:
    return dep["spec"]["template"]["spec"].get("containers") or []


def _commands(dep: dict) -> list[tuple[str, list]]:
    out = []
    for c in _containers(dep):
        cmd = c.get("command") or c.get("args") or []
        out.append((c.get("name", ""), list(cmd)))
    return out


def _pod_spec(obj: dict) -> dict:
    if obj["kind"] == "CronJob":
        return obj["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    return obj["spec"]["template"]["spec"]


def _volume_names_using_pvc(spec: dict, pvc: str) -> set[str]:
    names = set()
    for vol in spec.get("volumes") or []:
        claim = (vol.get("persistentVolumeClaim") or {}).get("claimName")
        if claim == pvc:
            names.add(vol["name"])
    return names


def _find_dep_for_command(by_kind, command: list[str]):
    for dep in by_kind.get("Deployment", []):
        for c in dep["spec"]["template"]["spec"].get("containers") or []:
            if (c.get("command") or []) == command:
                return dep, c
    return None, None


def _api_dep(by_kind, inventory):
    return _find_dep_for_command(by_kind, inventory["roles"]["api"]["command"])


def _worker_dep(by_kind, inventory):
    return _find_dep_for_command(by_kind, inventory["roles"]["worker"]["command"])


def _proxy_dep(by_kind, inventory):
    image = inventory["roles"]["proxy"]["image"]
    for dep in by_kind.get("Deployment", []):
        for c in dep["spec"]["template"]["spec"].get("containers") or []:
            if c.get("image") == image:
                return dep, c
    return None, None


def _cleanup_job(by_kind, inventory):
    role = inventory["roles"]["cleanup"]
    for job in by_kind.get("CronJob", []):
        if job["spec"].get("schedule") != role["schedule"]:
            continue
        if job["spec"].get("concurrencyPolicy") != role["concurrency_policy"]:
            continue
        containers = (
            job["spec"]["jobTemplate"]["spec"]["template"]["spec"].get("containers") or []
        )
        if any((c.get("command") or []) == role["command"] for c in containers):
            return job
    return None


def _all_pod_templates(by_kind):
    for dep in by_kind.get("Deployment", []):
        yield "Deployment", dep["metadata"]["name"], dep["spec"]["template"]["spec"]
    for job in by_kind.get("CronJob", []):
        yield (
            "CronJob",
            job["metadata"]["name"],
            job["spec"]["jobTemplate"]["spec"]["template"]["spec"],
        )


def _parse_memory(value: str) -> int:
    text = str(value)
    if text.endswith("Gi"):
        return int(float(text[:-2]) * 1024 ** 3)
    if text.endswith("Mi"):
        return int(float(text[:-2]) * 1024 ** 2)
    if text.endswith("Ki"):
        return int(float(text[:-2]) * 1024)
    return int(text)



def test_manifest_directory_exists():
    """Agent must leave Kubernetes manifests under /app/k8s."""
    assert Path("/app/k8s").is_dir()


def test_manifest_directory_has_yaml():
    """At least one YAML manifest must be present for verification."""
    files = list(Path("/app/k8s").rglob("*.yaml")) + list(Path("/app/k8s").rglob("*.yml"))
    assert files

def test_namespace_matches_inventory(by_kind, inventory):
    """Namespace object must match the inventoried namespace name."""
    names = [o["metadata"]["name"] for o in by_kind.get("Namespace", [])]
    assert inventory["namespace"] in names


def test_no_all_in_one_deployment(by_kind):
    """Reject a single Deployment that still models the monolith name alone."""
    deps = by_kind.get("Deployment", [])
    assert len(deps) >= 3
    monolith = [d for d in deps if d["metadata"]["name"] == "claims-upload"]
    assert not monolith, "remove the all-in-one claims-upload Deployment"


def test_api_deployment_command(by_kind, inventory):
    """API Deployment must run the inventoried serve command."""
    want = inventory["roles"]["api"]["command"]
    found = False
    for dep in by_kind.get("Deployment", []):
        for name, cmd in _commands(dep):
            if cmd == want:
                found = True
                assert dep["metadata"]["namespace"] == inventory["namespace"]
    assert found, f"no Deployment runs {want}"


def test_worker_deployment_command(by_kind, inventory):
    """Worker Deployment must run the inventoried worker command."""
    want = inventory["roles"]["worker"]["command"]
    found = any(
        cmd == want
        for dep in by_kind.get("Deployment", [])
        for _, cmd in _commands(dep)
    )
    assert found, f"no Deployment runs {want}"


def test_api_and_worker_are_separate_deployments(by_kind, inventory):
    """API and worker commands must not share one Pod template."""
    api = inventory["roles"]["api"]["command"]
    worker = inventory["roles"]["worker"]["command"]
    for dep in by_kind.get("Deployment", []):
        cmds = [cmd for _, cmd in _commands(dep)]
        if api in cmds and worker in cmds:
            raise AssertionError(
                f"{dep['metadata']['name']} still co-locates api and worker"
            )

def test_pvc_matches_inventory(by_kind, inventory):
    """PVC name, access mode, size, and storage class must match inventory."""
    storage = inventory["storage"]
    pvcs = by_kind.get("PersistentVolumeClaim", [])
    assert pvcs, "missing PersistentVolumeClaim"
    pvc = next(p for p in pvcs if p["metadata"]["name"] == storage["pvc_name"])
    spec = pvc["spec"]
    assert storage["access_modes"][0] in (spec.get("accessModes") or [])
    assert spec.get("storageClassName") == storage["storage_class"]
    assert spec["resources"]["requests"]["storage"] == storage["size"]


def test_api_worker_cleanup_mount_pvc(by_kind, inventory):
    """API, worker, and cleanup must mount the shared upload PVC."""
    pvc = inventory["storage"]["pvc_name"]
    mount_path = inventory["roles"]["api"]["mounts"][0]["path"]
    api_cmd = inventory["roles"]["api"]["command"]
    worker_cmd = inventory["roles"]["worker"]["command"]
    cleanup_cmd = inventory["roles"]["cleanup"]["command"]

    def role_ok(obj: dict, want_cmd: list[str]) -> bool:
        spec = _pod_spec(obj)
        vol_names = _volume_names_using_pvc(spec, pvc)
        if not vol_names:
            return False
        for c in spec.get("containers") or []:
            cmd = c.get("command") or []
            if cmd != want_cmd:
                continue
            mounts = {m.get("name"): m.get("mountPath") for m in c.get("volumeMounts") or []}
            return any(mounts.get(v) == mount_path for v in vol_names)
        return False

    assert any(role_ok(d, api_cmd) for d in by_kind.get("Deployment", []))
    assert any(role_ok(d, worker_cmd) for d in by_kind.get("Deployment", []))
    assert any(role_ok(c, cleanup_cmd) for c in by_kind.get("CronJob", []))


def test_no_empty_dir_for_uploads_on_api(by_kind, inventory):
    """API upload mount path must not be backed by emptyDir (INC-4412)."""
    api_cmd = inventory["roles"]["api"]["command"]
    upload_path = inventory["roles"]["api"]["mounts"][0]["path"]
    for dep in by_kind.get("Deployment", []):
        spec = dep["spec"]["template"]["spec"]
        api_containers = [
            c for c in spec.get("containers") or [] if (c.get("command") or []) == api_cmd
        ]
        if not api_containers:
            continue
        mount_names = set()
        for c in api_containers:
            for m in c.get("volumeMounts") or []:
                if m.get("mountPath") == upload_path:
                    mount_names.add(m.get("name"))
        assert mount_names, "api missing upload volumeMount"
        for vol in spec.get("volumes") or []:
            if vol.get("name") in mount_names:
                assert "emptyDir" not in vol, "api upload path still uses emptyDir"
                assert "persistentVolumeClaim" in vol


def test_secret_keys_present(by_kind, inventory):
    """Secret object must define inventoried secret keys."""
    secrets = by_kind.get("Secret", [])
    assert secrets, "missing Secret"
    keys = set()
    for secret in secrets:
        keys.update((secret.get("data") or {}).keys())
        keys.update((secret.get("stringData") or {}).keys())
    for key in inventory["secret_keys"]:
        assert key in keys


def test_workloads_use_secretref_not_literal_password(by_kind, inventory):
    """Deployments must not hard-code DB_PASSWORD/SIGNING_KEY values."""
    forbidden = set(inventory["secret_keys"])
    for dep in by_kind.get("Deployment", []):
        for c in dep["spec"]["template"]["spec"].get("containers") or []:
            for env in c.get("env") or []:
                if env.get("name") in forbidden and "value" in env:
                    raise AssertionError(
                        f"{dep['metadata']['name']}/{c.get('name')} hard-codes {env['name']}"
                    )
            names = {e.get("name") for e in c.get("env") or []}
            env_from = c.get("envFrom") or []
            if forbidden & names:
                # named env entries must be valueFrom secretKeyRef
                for env in c.get("env") or []:
                    if env.get("name") in forbidden:
                        assert "valueFrom" in env and "secretKeyRef" in env["valueFrom"]
            elif env_from:
                assert any("secretRef" in e for e in env_from)

def test_api_replicas(by_kind, inventory):
    """API Deployment replica count must match inventory."""
    dep, _ = _find_dep_for_command(by_kind, inventory["roles"]["api"]["command"])
    assert dep is not None
    assert dep["spec"].get("replicas") == inventory["availability"]["api_replicas"]


def test_worker_replicas(by_kind, inventory):
    """Worker Deployment replica count must match inventory."""
    dep, _ = _find_dep_for_command(by_kind, inventory["roles"]["worker"]["command"])
    assert dep is not None
    assert dep["spec"].get("replicas") == inventory["availability"]["worker_replicas"]


def test_api_has_http_probes(by_kind, inventory):
    """API container must define HTTP readiness and liveness probes."""
    role = inventory["roles"]["api"]
    dep, container = _find_dep_for_command(by_kind, role["command"])
    assert container is not None
    ready = container.get("readinessProbe") or {}
    live = container.get("livenessProbe") or {}
    assert ready.get("httpGet", {}).get("path") == role["ready_path"]
    assert live.get("httpGet", {}).get("path") == role["health_path"]


def test_api_resources(by_kind, inventory):
    """API resource requests/limits must match inventory envelopes."""
    want = inventory["resources"]["api"]
    dep, container = _find_dep_for_command(by_kind, inventory["roles"]["api"]["command"])
    assert container is not None
    res = container.get("resources") or {}
    assert res.get("requests") == want["requests"]
    assert res.get("limits") == want["limits"]


def test_worker_resources(by_kind, inventory):
    """Worker resource requests/limits must match inventory envelopes."""
    want = inventory["resources"]["worker"]
    dep, container = _find_dep_for_command(by_kind, inventory["roles"]["worker"]["command"])
    assert container is not None
    res = container.get("resources") or {}
    assert res.get("requests") == want["requests"]
    assert res.get("limits") == want["limits"]


def test_api_pdb(by_kind, inventory):
    """API PodDisruptionBudget minAvailable must match inventory."""
    pdbs = by_kind.get("PodDisruptionBudget", [])
    assert pdbs, "missing PodDisruptionBudget"
    want = inventory["availability"]["api_pdb_min_available"]
    assert any((p.get("spec") or {}).get("minAvailable") == want for p in pdbs)

def test_cleanup_cronjob(by_kind, inventory):
    """CronJob schedule, concurrency, and command must match inventory."""
    role = inventory["roles"]["cleanup"]
    jobs = by_kind.get("CronJob", [])
    assert jobs, "missing CronJob for cleanup"
    matched = False
    for job in jobs:
        spec = job["spec"]
        if spec.get("schedule") != role["schedule"]:
            continue
        if spec.get("concurrencyPolicy") != role["concurrency_policy"]:
            continue
        containers = (
            spec["jobTemplate"]["spec"]["template"]["spec"].get("containers") or []
        )
        for c in containers:
            if (c.get("command") or []) == role["command"]:
                matched = True
                assert job["metadata"]["namespace"] == inventory["namespace"]
                # Shared upload volume must be the inventoried PVC, not emptyDir.
                vols = spec["jobTemplate"]["spec"]["template"]["spec"].get("volumes") or []
                assert any(
                    (v.get("persistentVolumeClaim") or {}).get("claimName")
                    == inventory["storage"]["pvc_name"]
                    for v in vols
                )
    assert matched, "no CronJob matches inventoried cleanup schedule+Forbid+command"

def test_proxy_deployment_and_service(by_kind, inventory):
    """Proxy Deployment image/port and Service must front the API Service."""
    role = inventory["roles"]["proxy"]
    deps = by_kind.get("Deployment", [])
    proxy_dep = None
    for dep in deps:
        for c in dep["spec"]["template"]["spec"].get("containers") or []:
            if c.get("image") == role["image"]:
                proxy_dep = dep
                ports = [p.get("containerPort") for p in c.get("ports") or []]
                assert role["container_port"] in ports
    assert proxy_dep is not None, "missing proxy Deployment"

    services = by_kind.get("Service", [])
    api_svc = role["upstream_service"]
    assert any(s["metadata"]["name"] == api_svc for s in services), (
        f"missing upstream Service {api_svc}"
    )
    proxy_svcs = [
        s
        for s in services
        if s["metadata"].get("labels", {}).get("app.kubernetes.io/component")
        == "proxy"
        or s["metadata"]["name"] in {"claims-upload-proxy", "claims-upload"}
    ]
    assert proxy_svcs, "missing proxy Service"


def test_proxy_upstream_env_matches_inventory(by_kind, inventory):
    """Proxy UPSTREAM env must point at inventoried API Service:port."""
    role = inventory["roles"]["proxy"]
    want = f"{role['upstream_service']}:{role['upstream_port']}"
    found = False
    for dep in by_kind.get("Deployment", []):
        for c in dep["spec"]["template"]["spec"].get("containers") or []:
            if c.get("image") != role["image"]:
                continue
            for env in c.get("env") or []:
                if env.get("name") == "UPSTREAM" and env.get("value") == want:
                    found = True
    assert found, f"proxy missing UPSTREAM={want}"


def test_log_forwarder_sidecar_on_api_and_worker(by_kind, inventory):
    """API and worker pods must include the inventoried log-forwarder sidecar."""
    fwd = inventory["roles"]["log-forwarder"]["image"]
    api_cmd = inventory["roles"]["api"]["command"]
    worker_cmd = inventory["roles"]["worker"]["command"]

    def has_sidecar_with(command: list[str]) -> bool:
        for dep in by_kind.get("Deployment", []):
            containers = dep["spec"]["template"]["spec"].get("containers") or []
            cmds = [c.get("command") or [] for c in containers]
            images = [c.get("image") for c in containers]
            if command in cmds and fwd in images:
                return True
        return False

    assert has_sidecar_with(api_cmd)
    assert has_sidecar_with(worker_cmd)


def test_api_scrape_annotation(by_kind, inventory):
    """API pods should advertise Prometheus scrape annotations."""
    api_cmd = inventory["roles"]["api"]["command"]
    for dep in by_kind.get("Deployment", []):
        containers = dep["spec"]["template"]["spec"].get("containers") or []
        if not any((c.get("command") or []) == api_cmd for c in containers):
            continue
        ann = (
            dep["spec"]["template"]
            .get("metadata", {})
            .get("annotations", {})
        )
        assert ann.get("prometheus.io/scrape") in {"true", "True", True}
        return
    raise AssertionError("API Deployment missing scrape annotations")

def test_service_account_exists(by_kind, inventory):
    """Named ServiceAccount from inventory must exist in the namespace."""
    want = inventory["service_account"]
    accounts = by_kind.get("ServiceAccount", [])
    assert any(a["metadata"]["name"] == want for a in accounts)


def test_workloads_use_service_account(by_kind, inventory):
    """API/worker/cleanup/proxy pod templates must use the inventoried ServiceAccount."""
    want = inventory["service_account"]
    for kind, name, spec in _all_pod_templates(by_kind):
        assert spec.get("serviceAccountName") == want, f"{kind}/{name} missing serviceAccountName"


def test_no_privileged_or_host_path(by_kind, inventory):
    """Privileged containers and hostPath volumes are forbidden."""
    for kind, name, spec in _all_pod_templates(by_kind):
        for vol in spec.get("volumes") or []:
            assert "hostPath" not in vol, f"{kind}/{name} uses hostPath"
        for c in spec.get("containers") or []:
            sc = c.get("securityContext") or {}
            assert sc.get("privileged") is not True, f"{kind}/{name}/{c.get('name')} privileged"


def test_container_security_context(by_kind, inventory):
    """Containers must drop ALL caps, deny privilege escalation, and use read-only root FS."""
    sec = inventory["security"]
    for kind, name, spec in _all_pod_templates(by_kind):
        for c in spec.get("containers") or []:
            sc = c.get("securityContext") or {}
            assert sc.get("allowPrivilegeEscalation") is False, f"{kind}/{name}/{c.get('name')}"
            assert sc.get("readOnlyRootFilesystem") is True, f"{kind}/{name}/{c.get('name')}"
            drop = ((sc.get("capabilities") or {}).get("drop")) or []
            assert set(sec["capabilities_drop"]).issubset(set(drop)), f"{kind}/{name}/{c.get('name')}"


def test_api_required_pod_anti_affinity(by_kind, inventory):
    """API Deployment must require pod anti-affinity on hostname (INC-4825)."""
    dep, _ = _api_dep(by_kind, inventory)
    assert dep is not None
    paa = (
        (dep["spec"]["template"]["spec"].get("affinity") or {})
        .get("podAntiAffinity")
        or {}
    )
    required = paa.get("requiredDuringSchedulingIgnoredDuringExecution") or []
    assert required, "API missing required podAntiAffinity"
    assert any(r.get("topologyKey") == "kubernetes.io/hostname" for r in required)


def test_api_rolling_update(by_kind, inventory):
    """API RollingUpdate maxUnavailable/maxSurge must match inventory."""
    dep, _ = _api_dep(by_kind, inventory)
    assert dep is not None
    want = inventory["availability"]["api_rolling_update"]
    ru = (dep["spec"].get("strategy") or {}).get("rollingUpdate") or {}
    assert ru.get("maxUnavailable") == want["maxUnavailable"]
    assert ru.get("maxSurge") == want["maxSurge"]


def test_network_policy_api_ingress_from_proxy(by_kind, inventory):
    """NetworkPolicy must admit API port only from proxy component pods (INC-4811)."""
    np_cfg = inventory["network_policy"]
    policies = by_kind.get("NetworkPolicy", [])
    assert policies, "missing NetworkPolicy"
    matched = False
    for pol in policies:
        if pol["metadata"]["name"] != np_cfg["name"]:
            continue
        matched = True
        spec = pol["spec"]
        sel = (spec.get("podSelector") or {}).get("matchLabels") or {}
        assert sel.get("app.kubernetes.io/component") == np_cfg["api_component"]
        assert "Ingress" in (spec.get("policyTypes") or [])
        ingress = spec.get("ingress") or []
        assert ingress, "NetworkPolicy has no ingress rules"
        ok = False
        for rule in ingress:
            ports = [p.get("port") for p in rule.get("ports") or []]
            if np_cfg["api_port"] not in ports:
                continue
            for src in rule.get("from") or []:
                labels = (src.get("podSelector") or {}).get("matchLabels") or {}
                if labels.get("app.kubernetes.io/component") in np_cfg["allow_from_components"]:
                    ok = True
        assert ok, "API ingress does not allow proxy component"
    assert matched, f"NetworkPolicy {np_cfg['name']} not found"


def test_configmap_and_secret_names(by_kind, inventory):
    """ConfigMap/Secret object names must match inventory."""
    cms = [o["metadata"]["name"] for o in by_kind.get("ConfigMap", [])]
    secrets = [o["metadata"]["name"] for o in by_kind.get("Secret", [])]
    assert inventory["config_map"] in cms
    assert inventory["secret"] in secrets
    cm = next(o for o in by_kind["ConfigMap"] if o["metadata"]["name"] == inventory["config_map"])
    for key in inventory["config_keys"]:
        assert key in (cm.get("data") or {})

def test_all_objects_share_inventory_namespace(objects, inventory):
    """Every namespaced object must live in the inventoried namespace."""
    ns = inventory["namespace"]
    for obj in objects:
        if obj.get("kind") == "Namespace":
            continue
        meta = obj.get("metadata") or {}
        assert meta.get("namespace") == ns, f"{obj.get('kind')}/{meta.get('name')} wrong namespace"


def test_upload_root_config_matches_mount_path(by_kind, inventory):
    """ConfigMap UPLOAD_ROOT must equal the inventoried upload mount path."""
    cm_name = inventory["config_map"]
    key = inventory["config_upload_root_key"]
    path = inventory["roles"]["api"]["mounts"][0]["path"]
    cm = next(o for o in by_kind["ConfigMap"] if o["metadata"]["name"] == cm_name)
    assert (cm.get("data") or {}).get(key) == path


def test_port_chain_api_service_policy_proxy_scrape(by_kind, inventory):
    """API containerPort, Service port, NetworkPolicy port, scrape port, proxy upstream must agree."""
    port = inventory["roles"]["api"]["container_port"]
    dep, container = _api_dep(by_kind, inventory)
    assert dep is not None and container is not None
    cports = [p.get("containerPort") for p in container.get("ports") or []]
    assert port in cports

    svc_name = inventory["roles"]["proxy"]["upstream_service"]
    svc = next(s for s in by_kind["Service"] if s["metadata"]["name"] == svc_name)
    sports = [p.get("port") for p in svc["spec"].get("ports") or []]
    assert port in sports
    assert inventory["roles"]["proxy"]["upstream_port"] == port

    np = next(
        p for p in by_kind["NetworkPolicy"] if p["metadata"]["name"] == inventory["network_policy"]["name"]
    )
    nports = [
        p.get("port")
        for rule in np["spec"].get("ingress") or []
        for p in rule.get("ports") or []
    ]
    assert port in nports
    assert inventory["network_policy"]["api_port"] == port

    ann = (dep["spec"]["template"].get("metadata") or {}).get("annotations") or {}
    assert str(ann.get("prometheus.io/port")) == str(port)

    _, proxy_c = _proxy_dep(by_kind, inventory)
    assert proxy_c is not None
    upstream = next(e for e in proxy_c.get("env") or [] if e.get("name") == "UPSTREAM")
    assert upstream.get("value") == f"{svc_name}:{port}"


def test_selector_chain_service_pdb_networkpolicy(by_kind, inventory):
    """Service, PDB, and NetworkPolicy selectors must match the API pod labels."""
    dep, _ = _api_dep(by_kind, inventory)
    assert dep is not None
    pod_labels = (dep["spec"]["template"].get("metadata") or {}).get("labels") or {}
    comp_key = inventory["components"]["label_key"]
    assert pod_labels.get(comp_key) == inventory["components"]["api"]
    for key, value in inventory["labels"].items():
        assert pod_labels.get(key) == value

    svc_name = inventory["roles"]["proxy"]["upstream_service"]
    svc = next(s for s in by_kind["Service"] if s["metadata"]["name"] == svc_name)
    for key, value in (svc["spec"].get("selector") or {}).items():
        assert pod_labels.get(key) == value, f"Service selector {key} drifts from API pods"

    pdb = next(
        p
        for p in by_kind["PodDisruptionBudget"]
        if (p.get("spec") or {}).get("minAvailable") == inventory["availability"]["api_pdb_min_available"]
    )
    pdb_labels = ((pdb.get("spec") or {}).get("selector") or {}).get("matchLabels") or {}
    for key, value in pdb_labels.items():
        assert pod_labels.get(key) == value, f"PDB selector {key} drifts from API pods"

    np = next(
        p for p in by_kind["NetworkPolicy"] if p["metadata"]["name"] == inventory["network_policy"]["name"]
    )
    np_labels = ((np.get("spec") or {}).get("podSelector") or {}).get("matchLabels") or {}
    for key, value in np_labels.items():
        assert pod_labels.get(key) == value, f"NetworkPolicy selector {key} drifts from API pods"


def test_networkpolicy_from_matches_proxy_pod_labels(by_kind, inventory):
    """NetworkPolicy ingress.from must select the proxy Deployment's pod labels."""
    proxy_dep, _ = _proxy_dep(by_kind, inventory)
    assert proxy_dep is not None
    proxy_labels = (proxy_dep["spec"]["template"].get("metadata") or {}).get("labels") or {}
    comp_key = inventory["components"]["label_key"]
    assert proxy_labels.get(comp_key) == inventory["components"]["proxy"]

    np = next(
        p for p in by_kind["NetworkPolicy"] if p["metadata"]["name"] == inventory["network_policy"]["name"]
    )
    matched = False
    for rule in np["spec"].get("ingress") or []:
        for src in rule.get("from") or []:
            labels = (src.get("podSelector") or {}).get("matchLabels") or {}
            if not labels:
                continue
            if all(proxy_labels.get(k) == v for k, v in labels.items()):
                matched = True
    assert matched, "NetworkPolicy from selector does not match proxy pod labels"


def test_anti_affinity_selector_matches_api_labels(by_kind, inventory):
    """Required anti-affinity labelSelector must target the same API component labels."""
    dep, _ = _api_dep(by_kind, inventory)
    assert dep is not None
    pod_labels = (dep["spec"]["template"].get("metadata") or {}).get("labels") or {}
    required = (
        (dep["spec"]["template"]["spec"].get("affinity") or {})
        .get("podAntiAffinity")
        or {}
    ).get("requiredDuringSchedulingIgnoredDuringExecution") or []
    assert required
    sel = (required[0].get("labelSelector") or {}).get("matchLabels") or {}
    assert sel, "anti-affinity labelSelector empty"
    for key, value in sel.items():
        assert pod_labels.get(key) == value


def test_shared_pvc_claim_name_identical(by_kind, inventory):
    """API, worker, and cleanup must all claim the same inventoried PVC name."""
    pvc = inventory["storage"]["pvc_name"]

    def claim_names(spec):
        return {
            (v.get("persistentVolumeClaim") or {}).get("claimName")
            for v in spec.get("volumes") or []
            if "persistentVolumeClaim" in v
        }

    api_dep, _ = _api_dep(by_kind, inventory)
    worker_dep, _ = _worker_dep(by_kind, inventory)
    cleanup = _cleanup_job(by_kind, inventory)
    assert api_dep and worker_dep and cleanup
    api_claims = claim_names(api_dep["spec"]["template"]["spec"])
    worker_claims = claim_names(worker_dep["spec"]["template"]["spec"])
    cleanup_claims = claim_names(cleanup["spec"]["jobTemplate"]["spec"]["template"]["spec"])
    assert pvc in api_claims and pvc in worker_claims and pvc in cleanup_claims
    assert api_claims & worker_claims & cleanup_claims >= {pvc}


def test_envfrom_names_match_config_and_secret_objects(by_kind, inventory):
    """API/worker envFrom refs must name ConfigMap/Secret objects that actually exist."""
    cm = inventory["config_map"]
    secret = inventory["secret"]
    assert any(o["metadata"]["name"] == cm for o in by_kind.get("ConfigMap", []))
    assert any(o["metadata"]["name"] == secret for o in by_kind.get("Secret", []))

    for dep, _ in (_api_dep(by_kind, inventory), _worker_dep(by_kind, inventory)):
        assert dep is not None
        # Check the primary app container (first with envFrom)
        found = False
        for c in dep["spec"]["template"]["spec"].get("containers") or []:
            env_from = c.get("envFrom") or []
            if not env_from:
                continue
            names_cm = {(e.get("configMapRef") or {}).get("name") for e in env_from}
            names_sec = {(e.get("secretRef") or {}).get("name") for e in env_from}
            if cm in names_cm and secret in names_sec:
                found = True
        assert found, f"{dep['metadata']['name']} missing envFrom to {cm}/{secret}"


def test_same_app_image_for_api_worker_cleanup(by_kind, inventory):
    """API, worker, and cleanup app containers must use the inventoried app image."""
    image = inventory["image"]
    api_dep, api_c = _api_dep(by_kind, inventory)
    worker_dep, worker_c = _worker_dep(by_kind, inventory)
    cleanup = _cleanup_job(by_kind, inventory)
    assert api_c["image"] == image
    assert worker_c["image"] == image
    cleanup_c = next(
        c
        for c in cleanup["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
        if (c.get("command") or []) == inventory["roles"]["cleanup"]["command"]
    )
    assert cleanup_c["image"] == image


def test_rolling_update_respects_pdb_floor(by_kind, inventory):
    """replicas - maxUnavailable must remain >= PDB minAvailable."""
    avail = inventory["availability"]
    replicas = avail["api_replicas"]
    max_unavail = avail["api_rolling_update"]["maxUnavailable"]
    min_avail = avail["api_pdb_min_available"]
    assert replicas - max_unavail >= min_avail

    dep, _ = _api_dep(by_kind, inventory)
    assert dep is not None
    assert dep["spec"].get("replicas") == replicas
    ru = (dep["spec"].get("strategy") or {}).get("rollingUpdate") or {}
    assert ru.get("maxUnavailable") == max_unavail
    pdb = next(
        p
        for p in by_kind["PodDisruptionBudget"]
        if (p.get("spec") or {}).get("minAvailable") == min_avail
    )
    assert pdb is not None


def test_worker_memory_limit_exceeds_api(by_kind, inventory):
    """Worker memory limit must exceed API memory limit (INC-4588 isolation intent)."""
    _, api_c = _api_dep(by_kind, inventory)
    _, worker_c = _worker_dep(by_kind, inventory)
    api_mem = _parse_memory(api_c["resources"]["limits"]["memory"])
    worker_mem = _parse_memory(worker_c["resources"]["limits"]["memory"])
    assert worker_mem > api_mem
    # Also pinned to inventory envelopes so agents cannot invent arbitrary values.
    assert api_c["resources"] == inventory["resources"]["api"]
    assert worker_c["resources"] == inventory["resources"]["worker"]


def test_pod_fs_group_matches_inventory(by_kind, inventory):
    """Workload pod securityContext.fsGroup must match inventory."""
    want = inventory["security"]["fs_group"]
    for dep, _ in (_api_dep(by_kind, inventory), _worker_dep(by_kind, inventory), _proxy_dep(by_kind, inventory)):
        assert dep is not None
        sc = dep["spec"]["template"]["spec"].get("securityContext") or {}
        assert sc.get("fsGroup") == want, f"{dep['metadata']['name']} missing fsGroup={want}"
    cleanup = _cleanup_job(by_kind, inventory)
    sc = cleanup["spec"]["jobTemplate"]["spec"]["template"]["spec"].get("securityContext") or {}
    assert sc.get("fsGroup") == want


def _resolve_named_port(container, port_ref):
    if isinstance(port_ref, int):
        return port_ref
    if isinstance(port_ref, str) and port_ref.isdigit():
        return int(port_ref)
    for p in container.get("ports") or []:
        if p.get("name") == port_ref:
            return p.get("containerPort")
    return port_ref


def test_deployment_selector_subset_of_pod_labels(by_kind, inventory):
    """Each Deployment selector must be a non-empty subset of its pod template labels."""
    for finder in (_api_dep, _worker_dep, _proxy_dep):
        dep, _ = finder(by_kind, inventory)
        assert dep is not None
        sel = (dep["spec"].get("selector") or {}).get("matchLabels") or {}
        pod = (dep["spec"]["template"].get("metadata") or {}).get("labels") or {}
        assert sel, f"{dep['metadata']['name']} has empty selector"
        for key, value in sel.items():
            assert pod.get(key) == value, f"{dep['metadata']['name']} selector {key} not on pods"


def test_volume_mount_name_path_claim_chain(by_kind, inventory):
    """Mount name/path must match inventory and resolve to the inventoried PVC claimName."""
    pvc = inventory["storage"]["pvc_name"]

    def check(spec, role_key):
        mount = inventory["roles"][role_key]["mounts"][0]
        mounts = {
            m["name"]: m.get("mountPath")
            for c in spec.get("containers") or []
            for m in c.get("volumeMounts") or []
        }
        assert mounts.get(mount["name"]) == mount["path"], f"{role_key} mount path/name drift"
        vols = {v["name"]: v for v in spec.get("volumes") or []}
        assert mount["name"] in vols, f"{role_key} volume name missing for mount"
        claim = (vols[mount["name"]].get("persistentVolumeClaim") or {}).get("claimName")
        assert claim == pvc, f"{role_key} claimName drifts from inventory PVC"

    api_dep, _ = _api_dep(by_kind, inventory)
    worker_dep, _ = _worker_dep(by_kind, inventory)
    cleanup = _cleanup_job(by_kind, inventory)
    assert api_dep and worker_dep and cleanup
    check(api_dep["spec"]["template"]["spec"], "api")
    check(worker_dep["spec"]["template"]["spec"], "worker")
    check(cleanup["spec"]["jobTemplate"]["spec"]["template"]["spec"], "cleanup")


def test_probe_paths_and_ports_match_inventory(by_kind, inventory):
    """API readiness/liveness paths and resolved ports must match inventory containerPort."""
    role = inventory["roles"]["api"]
    port = role["container_port"]
    _, container = _api_dep(by_kind, inventory)
    assert container is not None
    ready = (container.get("readinessProbe") or {}).get("httpGet") or {}
    live = (container.get("livenessProbe") or {}).get("httpGet") or {}
    assert ready.get("path") == role["ready_path"]
    assert live.get("path") == role["health_path"]
    assert _resolve_named_port(container, ready.get("port")) == port
    assert _resolve_named_port(container, live.get("port")) == port


def test_service_target_port_resolves_to_api_container_port(by_kind, inventory):
    """API Service targetPort must resolve to the same containerPort the API exposes."""
    port = inventory["roles"]["api"]["container_port"]
    _, container = _api_dep(by_kind, inventory)
    svc_name = inventory["roles"]["proxy"]["upstream_service"]
    svc = next(s for s in by_kind["Service"] if s["metadata"]["name"] == svc_name)
    target = (svc["spec"].get("ports") or [{}])[0].get("targetPort")
    assert _resolve_named_port(container, target) == port


def test_proxy_service_selector_matches_proxy_pods(by_kind, inventory):
    """Front-door Service selector must select the proxy Deployment pods."""
    dep, container = _proxy_dep(by_kind, inventory)
    assert dep is not None and container is not None
    pod_labels = (dep["spec"]["template"].get("metadata") or {}).get("labels") or {}
    port = inventory["roles"]["proxy"]["container_port"]
    proxy_svcs = [
        s
        for s in by_kind.get("Service", [])
        if any(p.get("port") == port for p in s["spec"].get("ports") or [])
        and s["metadata"]["name"] != inventory["roles"]["proxy"]["upstream_service"]
    ]
    assert proxy_svcs, "proxy Service not found"
    for svc in proxy_svcs:
        for key, value in (svc["spec"].get("selector") or {}).items():
            assert pod_labels.get(key) == value, f"proxy Service selector {key} drifts"


def test_component_labels_are_distinct_across_roles(by_kind, inventory):
    """api/worker/proxy/cleanup must carry distinct inventory component label values."""
    comp_key = inventory["components"]["label_key"]
    seen = {}

    def record(labels, role):
        value = labels.get(comp_key)
        assert value == inventory["components"][role], f"{role} component label mismatch"
        assert value not in seen, f"component label {value} reused by {seen[value]} and {role}"
        seen[value] = role

    api_dep, _ = _api_dep(by_kind, inventory)
    worker_dep, _ = _worker_dep(by_kind, inventory)
    proxy_dep, _ = _proxy_dep(by_kind, inventory)
    cleanup = _cleanup_job(by_kind, inventory)
    record((api_dep["spec"]["template"].get("metadata") or {}).get("labels") or {}, "api")
    record((worker_dep["spec"]["template"].get("metadata") or {}).get("labels") or {}, "worker")
    record((proxy_dep["spec"]["template"].get("metadata") or {}).get("labels") or {}, "proxy")
    record(
        (cleanup["spec"]["jobTemplate"]["spec"]["template"].get("metadata") or {}).get("labels") or {},
        "cleanup",
    )


def test_config_and_secret_key_sets_match_inventory(by_kind, inventory):
    """ConfigMap/Secret key sets must exactly match inventory, including UPLOAD_ROOT."""
    cm = next(o for o in by_kind["ConfigMap"] if o["metadata"]["name"] == inventory["config_map"])
    secret = next(o for o in by_kind["Secret"] if o["metadata"]["name"] == inventory["secret"])
    assert set((cm.get("data") or {}).keys()) == set(inventory["config_keys"])
    assert set((secret.get("data") or secret.get("stringData") or {}).keys()) == set(
        inventory["secret_keys"]
    )
    assert inventory["config_upload_root_key"] in inventory["config_keys"]


def test_service_account_name_chain(by_kind, inventory):
    """ServiceAccount object name must equal inventory and every workload's serviceAccountName."""
    sa = inventory["service_account"]
    assert any(o["metadata"]["name"] == sa for o in by_kind.get("ServiceAccount", []))
    for dep, _ in (_api_dep(by_kind, inventory), _worker_dep(by_kind, inventory), _proxy_dep(by_kind, inventory)):
        assert dep["spec"]["template"]["spec"].get("serviceAccountName") == sa
    cleanup = _cleanup_job(by_kind, inventory)
    assert (
        cleanup["spec"]["jobTemplate"]["spec"]["template"]["spec"].get("serviceAccountName") == sa
    )


def test_multi_writer_requires_shared_access_mode(by_kind, inventory):
    """Three writers on one claim imply the inventoried multi-writer access mode on the PVC."""
    modes = set(inventory["storage"]["access_modes"])
    assert "ReadWriteMany" in modes
    pvc = next(
        o for o in by_kind["PersistentVolumeClaim"] if o["metadata"]["name"] == inventory["storage"]["pvc_name"]
    )
    assert set(pvc["spec"].get("accessModes") or []) == modes
    # Shared claim already enforced elsewhere; this pins why RWX is required.
    api_dep, _ = _api_dep(by_kind, inventory)
    worker_dep, _ = _worker_dep(by_kind, inventory)
    cleanup = _cleanup_job(by_kind, inventory)
    assert api_dep and worker_dep and cleanup
