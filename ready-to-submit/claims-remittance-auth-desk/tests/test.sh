#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
echo 0 > /logs/verifier/reward.txt
TEST_DIR="${TEST_DIR:-/tests}"

pg_ctlcluster 15 main start
runuser -u postgres -- psql -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE claims_app LOGIN PASSWORD 'claims_local';
CREATE DATABASE claims OWNER claims_app;
SQL

export CLAIMS_DB_HOST=127.0.0.1
export CLAIMS_DB=claims@127.0.0.1:5432
export CLAIMS_DB_USER=claims_app
export CLAIMS_DB_PASSWORD=claims_local

pytest --ctrf /logs/verifier/ctrf.json -p no:cacheprovider "$TEST_DIR" -rA
if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
