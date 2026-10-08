#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
echo 0 > /logs/verifier/reward.txt

TARGET="${FLEET_ROOT:-/app/fleet-automation}"
if [ ! -d "$TARGET" ]; then
  echo "missing fleet artifact: $TARGET" >&2
  exit 0
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/tests"
ln -s "$TARGET" "$WORK/environment"
cp /tests/test_fleet_recovery.py "$WORK/tests/test_fleet_recovery.py"
cat > "$WORK/ansible.cfg" <<EOF
[defaults]
roles_path = $WORK/environment/roles
inventory = $WORK/environment/inventory/hosts.yml
retry_files_enabled = False
stdout_callback = default
interpreter_python = auto_silent
vault_password_file = $TARGET/.runtime-vault-pass
EOF
export ANSIBLE_CONFIG="$WORK/ansible.cfg"

python3 -m pytest -p no:cacheprovider \
  --ctrf /logs/verifier/ctrf.json \
  "$WORK/tests/test_fleet_recovery.py" -rA
if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
