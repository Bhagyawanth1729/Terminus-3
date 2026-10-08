# hris-midcycle-payroll-close

Mid-cycle payroll close for a local HRIS: effective-dated org transfers, FLSA overtime, leave accrual, attendance exceptions, and cutoff/retro. The starter ignores transfers until the next cycle, always applies non-exempt OT math, appends on a second close, and counts punches after cutoff.

## Layout

- `environment/hris/` — CLI, contract, SQLite schema/seed (12k employees), fake IdP, broken close
- `solution/` — corrected close/auth modules; `solve.sh` applies the E000001 transfer and closes 2026-W32
- `tests/` — separate verifier against register/retro/dump and live `hrctl` mutations

Difficulty in `task.toml` is provisional until both model families are measured.

## Local Harbor

```bash
stb harbor run -a oracle -p Terminus-Edition-3/hris-midcycle-payroll-close -o /tmp/e3-hris-jobs
stb harbor run -a nop -p Terminus-Edition-3/hris-midcycle-payroll-close -o /tmp/e3-hris-jobs
```
