#!/usr/bin/env bash
set -euo pipefail

install -m 0644 /solution/fixed/auth.py /app/hris/lib/auth.py
install -m 0644 /solution/fixed/close.py /app/hris/lib/close.py

/app/hris/bin/hrctl transfer \
  --employee E000001 \
  --effective 2026-08-04 \
  --cost-center CC-FIN-14 \
  --flsa exempt \
  --leave-plan PTO-EX

/app/hris/bin/hrctl close-payroll --period 2026-W32
/app/hris/bin/hrctl dump
