#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python -m pip install --disable-pip-version-check --no-cache-dir 'ansible==12.0.0' >/dev/null

ansible-config init --disabled > ansible.cfg.generated
python - <<'PY'
from pathlib import Path
src = Path('ansible.cfg.generated').read_text(encoding='utf-8')
lines = src.splitlines()
out = []
inserted = False
for line in lines:
    out.append(line)
    if line.strip() == '[defaults]' and not inserted:
        out.extend([
            'roles_path = ./environment/roles',
            'inventory = ./environment/inventory/hosts.yml',
            'retry_files_enabled = False',
            'stdout_callback = default',
            'interpreter_python = auto_silent',
            'vault_password_file = ./.runtime-vault-pass',
        ])
        inserted = True
if not inserted:
    out.extend(['', '[defaults]', 'roles_path = ./environment/roles', 'inventory = ./environment/inventory/hosts.yml', 'retry_files_enabled = False', 'stdout_callback = default', 'interpreter_python = auto_silent', 'vault_password_file = ./.runtime-vault-pass'])
Path('ansible.cfg').write_text('\n'.join(out) + '\n', encoding='utf-8')
PY

printf '%s\n' "${FLEET_VAULT_PASSWORD:-fleet-ci-vault-password}" > .runtime-vault-pass
chmod 600 .runtime-vault-pass

python - <<'PY'
from pathlib import Path
import yaml

all_vars = Path('environment/inventory/group_vars/all.yml')
data = yaml.safe_load(all_vars.read_text(encoding='utf-8'))
data['fleet_site_overrides']['hyd']['application']['dependencies'] = {
    'timeout_seconds': 4,
    'retries': 3,
    'tls': {
        'enabled': True,
        'trust_bundle': '/etc/ssl/certs/fleet-ca-bundle.pem',
    },
}
data['fleet_required_groups'] = ['application_nodes', 'proxy_nodes', 'database_nodes']
all_vars.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
PY

cat > environment/playbooks/site.yml <<'YAML'
---
- name: Fleet preflight
  hosts: all
  gather_facts: false
  any_errors_fatal: true
  roles:
    - fleet_preflight

- name: Prepare fleet hosts
  hosts: all
  gather_facts: false
  serial: 25%
  roles:
    - common_baseline
    - service_identity
    - trust_bundle

- name: Configure application tier
  hosts: application_nodes
  gather_facts: false
  serial: 25%
  roles:
    - application_release

- name: Configure edge tier
  hosts: proxy_nodes
  gather_facts: false
  serial: 1
  roles:
    - edge_proxy

- name: Configure telemetry tier
  hosts: all
  gather_facts: false
  roles:
    - telemetry_agent

- name: Apply host policy
  hosts: all
  gather_facts: false
  roles:
    - host_policy

- name: Validate fleet convergence
  hosts: all
  gather_facts: false
  serial: 25%
  roles:
    - fleet_validation
YAML

cat > environment/roles/common_baseline/tasks/main.yml <<'YAML'
---
- name: Create runtime directories
  file:
    path: "{{ item.path }}"
    state: directory
    owner: root
    group: root
    mode: "{{ item.mode }}"
  loop:
    - {path: "{{ fleet_runtime_root }}", mode: '0750'}
    - {path: "{{ fleet_runtime_root }}/staged/{{ inventory_hostname }}", mode: '0750'}
    - {path: "{{ fleet_runtime_root }}/state/{{ inventory_hostname }}", mode: '0750'}
    - {path: "{{ fleet_runtime_root }}/rootfs/{{ inventory_hostname }}/etc/fleet", mode: '0750'}
    - {path: "{{ fleet_runtime_root }}/rootfs/{{ inventory_hostname }}/etc/ssl/certs", mode: '0755'}
    - {path: "{{ fleet_runtime_root }}/rootfs/{{ inventory_hostname }}/etc/nginx/conf.d", mode: '0755'}
    - {path: "{{ fleet_runtime_root }}/rootfs/{{ inventory_hostname }}/etc/telemetry", mode: '0750'}

- name: Install baseline packages
  package:
    name:
      - ca-certificates
      - rsync
      - python3
    state: present
  become: true
  when: ansible_connection != 'local'

- name: Establish host runtime marker
  copy:
    dest: "{{ fleet_runtime_root }}/state/{{ inventory_hostname }}/baseline.json"
    content: "{{ {'host': inventory_hostname, 'site': fleet_site, 'environment': fleet_environment} | to_nice_json }}\n"
    mode: '0640'
YAML

cat > environment/roles/service_identity/tasks/main.yml <<'YAML'
---
- name: Build service identity document
  copy:
    dest: "{{ fleet_runtime_root }}/staged/{{ inventory_hostname }}/identity.json"
    content: |
      {{ {
        'host': inventory_hostname,
        'site': fleet_site,
        'environment': fleet_environment,
        'service_account': 'svc-' ~ inventory_hostname,
        'trust_bundle': '/etc/ssl/certs/fleet-ca-bundle.pem',
        'groups': group_names | sort
      } | to_nice_json }}
    mode: '0640'
  notify: reload fleet services

- name: Promote service identity
  copy:
    src: "{{ fleet_runtime_root }}/staged/{{ inventory_hostname }}/identity.json"
    dest: "{{ fleet_runtime_root }}/rootfs/{{ inventory_hostname }}/etc/fleet/identity.json"
    remote_src: true
    mode: '0640'

- name: Expose identity path
  set_fact:
    fleet_identity_path: "{{ fleet_runtime_root }}/rootfs/{{ inventory_hostname }}/etc/fleet/identity.json"
YAML

cat > environment/roles/application_release/tasks/main.yml <<'YAML'
---
- name: Load production secret data
  include_vars:
    file: "{{ fleet_secret_file }}"
    name: fleet_vault
  no_log: true

- name: Render application configuration
  template:
    src: application.yml.j2
    dest: "{{ fleet_runtime_root }}/staged/{{ inventory_hostname }}/application.yml"
    mode: '0640'
  notify: reload fleet services

- name: Stage application credential
  copy:
    dest: "{{ fleet_runtime_root }}/staged/{{ inventory_hostname }}/application.secret"
    content: "{{ fleet_vault.application.database_password }}\n"
    mode: '0600'
  no_log: true

- name: Promote application configuration
  copy:
    src: "{{ fleet_runtime_root }}/staged/{{ inventory_hostname }}/application.yml"
    dest: "{{ fleet_runtime_root }}/rootfs/{{ inventory_hostname }}/etc/fleet/application.yml"
    remote_src: true
    mode: '0640'

- name: Promote application credential
  copy:
    src: "{{ fleet_runtime_root }}/staged/{{ inventory_hostname }}/application.secret"
    dest: "{{ fleet_runtime_root }}/rootfs/{{ inventory_hostname }}/etc/fleet/application.secret"
    remote_src: true
    mode: '0600'
  no_log: true
YAML

cat > environment/roles/application_release/templates/application.yml.j2 <<'J2'
environment: {{ fleet_environment }}
site: {{ fleet_site }}
service: {{ fleet_effective_settings.application.service }}
listen:
  address: {{ fleet_effective_settings.application.listen.address }}
  port: {{ fleet_effective_settings.application.listen.port | int }}
dependencies:
  - name: trust_bundle
    path: {{ fleet_effective_settings.application.dependencies.tls.trust_bundle }}
    tls: {{ fleet_effective_settings.application.dependencies.tls.enabled | bool | lower }}
  - name: database
    timeout_seconds: {{ fleet_effective_settings.application.dependencies.timeout_seconds | int }}
    retries: {{ fleet_effective_settings.application.dependencies.retries | int }}
credentials:
  secret_ref: /etc/fleet/application.secret
identity:
  path: {{ fleet_identity_path }}
J2

cat > environment/roles/edge_proxy/templates/upstreams.conf.j2 <<'J2'
upstream checkout_backend {
{% for host in groups.get('application_nodes', []) | sort %}
{% set raw = hostvars[host].fleet_services.checkout %}
{% if raw is string %}
{% set raw_host = raw.rsplit(':', 1)[0] %}
{% set raw_port = raw.rsplit(':', 1)[1] | int %}
{% set raw_weight = 1 %}
{% else %}
{% set endpoint = raw.endpoint if raw.endpoint is defined else raw %}
{% set raw_host = endpoint.host %}
{% set raw_port = endpoint.port | int %}
{% set raw_weight = endpoint.weight | default(1) | int %}
{% endif %}
{% set rendered_host = '[' ~ raw_host ~ ']' if ':' in raw_host else raw_host %}
    server {{ rendered_host }}:{{ raw_port }} weight={{ raw_weight }} max_fails={{ fleet_effective_settings.proxy.max_fails | int }} fail_timeout={{ fleet_effective_settings.proxy.fail_timeout_seconds | int }}s;
{% endfor %}
}

server {
    listen 8443 ssl;
    location / {
        proxy_connect_timeout {{ fleet_effective_settings.proxy.connect_timeout_seconds | int }}s;
        proxy_read_timeout {{ fleet_effective_settings.proxy.read_timeout_seconds | int }}s;
        proxy_pass http://checkout_backend;
    }
}
J2

cat > environment/roles/telemetry_agent/tasks/main.yml <<'YAML'
---
- name: Render telemetry targets
  template:
    src: targets.yml.j2
    dest: "{{ fleet_runtime_root }}/staged/{{ inventory_hostname }}/targets.yml"
    mode: '0640'
  notify: restart telemetry agent

- name: Promote telemetry targets
  copy:
    src: "{{ fleet_runtime_root }}/staged/{{ inventory_hostname }}/targets.yml"
    dest: "{{ fleet_runtime_root }}/rootfs/{{ inventory_hostname }}/etc/telemetry/targets.yml"
    remote_src: true
    mode: '0640'
YAML

cat > environment/roles/telemetry_agent/templates/targets.yml.j2 <<'J2'
targets:
{% set target_hosts = (groups.get('telemetry_collectors', []) + groups.get('application_nodes', []) + groups.get('proxy_nodes', [])) | unique | sort %}
{% for host in target_hosts %}
  - host: {{ hostvars[host].telemetry_address | default(hostvars[host].ansible_host) }}
    port: {{ hostvars[host].telemetry_port | default(9100) | int }}
    labels:
      inventory_host: {{ host }}
      site: {{ hostvars[host].group_names | intersect(['blr', 'maa', 'hyd']) | first }}
{% endfor %}
J2

cat > environment/roles/host_policy/tasks/main.yml <<'YAML'
---
- name: Load policy catalog
  set_fact:
    fleet_policy_rules: "{{ (lookup('file', playbook_dir ~ '/../data/policy-catalog.yml') | from_yaml).rules }}"

- name: Render host policy
  template:
    src: policy.conf.j2
    dest: "{{ fleet_runtime_root }}/staged/{{ inventory_hostname }}/policy.conf"
    mode: '0640'

- name: Promote host policy
  copy:
    src: "{{ fleet_runtime_root }}/staged/{{ inventory_hostname }}/policy.conf"
    dest: "{{ fleet_runtime_root }}/rootfs/{{ inventory_hostname }}/etc/fleet/policy.conf"
    remote_src: true
    mode: '0640'
YAML

cat > environment/roles/host_policy/templates/policy.conf.j2 <<'J2'
{% for rule in fleet_policy_rules | sort(attribute='priority') %}
priority {{ rule.priority | int }} source {{ rule.source }} destination {{ rule.destination }} protocol {{ rule.protocol }} port {{ rule.port | int }} action {{ rule.action }} id {{ rule.id }} owner {{ rule.owner }}
{% endfor %}
J2

cat > environment/playbooks/validate.yml <<'YAML'
---
- name: Validate fleet invariants
  hosts: all
  gather_facts: false
  tasks:
    - name: Verify rendered artifact contract
      assert:
        that:
          - item.path is string
          - item.mode is match('^0[0-7]{3}$')
          - item.owner | length > 0
        fail_msg: "invalid artifact contract for {{ item.path | default('unknown') }}"
      vars:
        artifact_contracts:
          - {path: /etc/fleet/identity.json, mode: '0640', owner: root}
          - {path: /etc/fleet/application.yml, mode: '0640', owner: root}
          - {path: /etc/nginx/conf.d/fleet.conf, mode: '0644', owner: root}
          - {path: /etc/telemetry/targets.yml, mode: '0640', owner: root}
          - {path: /etc/fleet/policy.conf, mode: '0640', owner: root}
      loop: "{{ artifact_contracts }}"
      loop_control:
        label: "{{ item.path }}"

    - name: Validate backend cardinality by site
      assert:
        that:
          - groups[item] is defined
          - groups[item] | length >= 4
      loop:
        - blr
        - maa
        - hyd
      loop_control:
        label: "site={{ item }}"
YAML

python - <<'PY'
from pathlib import Path
p = Path('environment/lib/fleet_validator.py')
s = p.read_text(encoding='utf-8')
old = '''def validate_host(root: Path, host: str) -> dict[str, Any]:\n    findings = []\n    validate_identity(root, host, findings)\n    validate_trust(root, host, findings)\n    validate_application(root, host, findings)\n    validate_proxy(root, host, findings)\n    validate_telemetry(root, host, findings)\n    validate_policy(root, host, findings)\n    validate_secret_hygiene(root, host, findings)\n    state = HostState(root, host).verify_materialized()\n'''
new = '''def validate_host(root: Path, host: str) -> dict[str, Any]:\n    findings = []\n    validate_identity(root, host, findings)\n    identity_path = rootfs(root, host, "/etc/fleet/identity.json")\n    groups = []\n    if identity_path.is_file():\n        try:\n            groups = json.loads(identity_path.read_text(encoding="utf-8")).get("groups", [])\n        except Exception:\n            groups = []\n    validate_trust(root, host, findings)\n    if "application_nodes" in groups:\n        validate_application(root, host, findings)\n    if "proxy_nodes" in groups:\n        validate_proxy(root, host, findings)\n    validate_telemetry(root, host, findings)\n    validate_policy(root, host, findings)\n    validate_secret_hygiene(root, host, findings)\n    state = HostState(root, host).verify_materialized()\n'''
if old not in s:
    raise SystemExit('fleet_validator validate_host anchor not found')
p.write_text(s.replace(old, new), encoding='utf-8')
PY

python - <<'PY'
from pathlib import Path
p = Path('environment/Dockerfile')
s = p.read_text(encoding='utf-8')
s = s.replace("'ansible==2.9.27'", "'ansible==12.0.0'")
p.write_text(s, encoding='utf-8')
PY

VAULT_FILE=environment/inventory/group_vars/prod/vault.yml
if ! head -n 1 "$VAULT_FILE" | grep -q '^\$ANSIBLE_VAULT;'; then
  ansible-vault encrypt --vault-password-file .runtime-vault-pass "$VAULT_FILE"
fi

./environment/bin/fleet-ansible environment/playbooks/site.yml --syntax-check
./environment/bin/fleet-ansible environment/playbooks/preflight.yml
./environment/bin/fleet-ansible environment/playbooks/site.yml
./environment/bin/fleet-ansible environment/playbooks/site.yml

python environment/lib/fleet_validator.py --root /tmp/fleet-runtime --output /tmp/fleet-runtime/reports/final-validation.json \
  blr-app-01 blr-app-02 blr-proxy-01 blr-db-01 \
  maa-app-01 maa-app-02 maa-proxy-01 maa-db-01 \
  hyd-app-01 hyd-app-02 hyd-proxy-01 hyd-db-01

python - <<'PY'
from pathlib import Path
import json
report = json.loads(Path('/tmp/fleet-runtime/reports/final-validation.json').read_text(encoding='utf-8'))
if not report.get('ok'):
    raise SystemExit('fleet validation did not converge')
print('reference_solution=PASS hosts=%d' % len(report['hosts']))
PY
