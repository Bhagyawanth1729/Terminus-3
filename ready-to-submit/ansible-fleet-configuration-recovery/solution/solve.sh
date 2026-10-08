#!/usr/bin/env bash
set -euo pipefail

TARGET="${FLEET_ROOT:-/app/fleet-automation}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -d "$TARGET" ]]; then
  printf 'missing fleet runtime: %s\n' "$TARGET" >&2
  exit 1
fi

# Harbor's solution container may expose a Python/pip environment whose generated
# console scripts are not on PATH or are not importable through the inherited
# interpreter. Build an isolated controller environment at a deterministic path
# and use its real Ansible console scripts for the complete reference repair.
WORK="$(mktemp -d)"
cleanup() {
  if [[ -L "$TARGET/environment" ]]; then
    rm -f "$TARGET/environment"
  fi
  if [[ -L "$TARGET/ansible.cfg" ]]; then
    rm -f "$TARGET/ansible.cfg"
  fi
  if [[ -L "$TARGET/.runtime-vault-pass" ]]; then
    rm -f "$TARGET/.runtime-vault-pass"
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

python -m venv "$WORK/ansible-venv"
"$WORK/ansible-venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir 'ansible==12.0.0' >/dev/null
export PATH="$WORK/ansible-venv/bin:$PATH"
command -v ansible-config >/dev/null
command -v ansible-vault >/dev/null
command -v ansible-playbook >/dev/null

mkdir -p "$WORK/solution"
ln -s "$TARGET" "$WORK/environment"
cp "$HERE/repair.sh" "$WORK/solution/repair.sh"
chmod 0755 "$WORK/solution/repair.sh"

# The encrypted vars file already owns the top-level fleet_vault key. The
# historical repair wrapped include_vars with the same name again, producing
# fleet_vault.fleet_vault.* and aborting application credential staging. Keep
# the file's native namespace when executing the reference repair.
python - "$WORK/solution/repair.sh" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = '''  include_vars:\n    file: "{{ fleet_secret_file }}"\n    name: fleet_vault\n'''
new = '''  include_vars:\n    file: "{{ fleet_secret_file }}"\n'''
if text.count(old) != 1:
    raise SystemExit("application secret include_vars anchor not found exactly once")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
PY

# The historical reference repair was authored against the repository task
# layout where the runtime lives under environment/. Recreate that layout
# transiently while applying all mutations to the real runtime artifact.
if [[ ! -e "$TARGET/environment" ]]; then
  ln -s . "$TARGET/environment"
fi
: > "$WORK/ansible.cfg"
ln -s "$WORK/ansible.cfg" "$TARGET/ansible.cfg"
ln -s "$WORK/.runtime-vault-pass" "$TARGET/.runtime-vault-pass"

# Bind the generated project config explicitly so nested localhost commands in
# preflight observe the same controller configuration as fleet-ansible even
# when their working directory is not the project root.
export ANSIBLE_CONFIG="$WORK/ansible.cfg"

# repair.sh intentionally declares the same password source in project config
# and on the historical vault command line. Ansible 2.19 treats those as two
# default vault identities, so make the encryption identity explicit while
# preserving the inherited repair body and password source semantics.
export ANSIBLE_VAULT_ENCRYPT_IDENTITY=default
"$WORK/solution/repair.sh"

# Persist a runtime-native configuration after the transient repository-layout
# compatibility layer is removed.
cfg_tmp="$WORK/ansible.runtime.cfg"
cp -L "$TARGET/ansible.cfg" "$cfg_tmp"
sed -i \
  -e 's#roles_path = ./environment/roles#roles_path = ./roles#' \
  -e 's#inventory = ./environment/inventory/hosts.yml#inventory = ./inventory/hosts.yml#' \
  -e 's#vault_password_file = ./.runtime-vault-pass#vault_password_file = /app/fleet-automation/.runtime-vault-pass#' \
  "$cfg_tmp"
pass_tmp="$WORK/runtime-vault-pass"
cp -L "$TARGET/.runtime-vault-pass" "$pass_tmp"
rm -f "$TARGET/ansible.cfg" "$TARGET/.runtime-vault-pass" "$TARGET/environment"
install -m 0644 "$cfg_tmp" "$TARGET/ansible.cfg"
install -m 0600 "$pass_tmp" "$TARGET/.runtime-vault-pass"

cd "$TARGET"
export ANSIBLE_CONFIG="$TARGET/ansible.cfg"
./bin/fleet-ansible playbooks/site.yml --syntax-check
printf 'reference_solution=PASS target=%s\n' "$TARGET"
