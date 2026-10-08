# Payroll close contract

Operator: `/app/hris/bin/hrctl`

Runtime paths (env overrides allowed):

| env | default |
| --- | --- |
| `HRIS_DB` | `/app/hris/var/hris.db` |
| `HRIS_OUT` | `/app/hris/out` |
| `HRIS_TOKEN` | `/app/hris/var/idp.token` |
| `HRIS_IDP` | `/app/hris/var/idp.json` |

Commands:

- `hrctl transfer --employee ID --effective YYYY-MM-DD --cost-center CC --flsa exempt|non_exempt --leave-plan PLAN`
- `hrctl punch --employee ID --at ISO-8601 --direction in|out`
- `hrctl leave --employee ID --start YYYY-MM-DD --end YYYY-MM-DD --hours N --status approved|pending|denied`
- `hrctl close-payroll --period PERIOD_ID`
- `hrctl dump`

Every command except `dump` requires the token file to match `issuer.subject.audience.v1` built from `/app/hris/var/idp.json`. Missing or wrong token exits 3 and writes nothing. This is a local fake IdP file, not a network call.

Unknown verbs exit 2 without opening a close.

## Period

Row in `pay_periods`. `start_date` and `end_date` are inclusive calendar dates (UTC). `cutoff_at` is an ISO-8601 UTC timestamp. `work_days` counts Monday–Friday inside the period.

Punches with `punched_at` strictly after `cutoff_at` are ignored for hours, exceptions, and OT.

A period already present in `payroll_closes` cannot be closed again. The second `close-payroll` exits 4, leaves both JSON outputs byte-identical, and does not insert another close row.

## Effective-dated assignment

`assignments.effective_date` is inclusive; `end_date` is exclusive or NULL. The assignment for a calendar date is the row with the greatest `effective_date <= date` that is still open. `transfer` closes the open row at the new effective date and inserts the new row.

A transfer whose `effective_date` is on or before the period end (and on or after period start) is in-period. Close must honor it for that period: FLSA class, leave plan/accrual, and cost center all change on the effective date together. The register line reports cost center and `flsa_status` as of period end. The retro journal records the split.

## Hours and FLSA

Pair `in`/`out` punches per employee in timestamp order. An `in` without a later `out` is a `missing_out` exception and contributes 0 hours. Hours belong to the UTC date of the `in` punch.

Walk hours chronologically across work dates:

- the first 40.00 hours in the period are regular
- remaining hours are overtime

Pay:

- non-exempt regular: `hours * hourly_rate`
- non-exempt overtime: `hours * hourly_rate * 1.5`
- exempt regular: `salary_per_period * exempt_work_days / work_days` (salary covers the exempt days; do not also pay hourly)
- exempt overtime: `0` hours and `0` pay (even when clock hours exceed 40)

Rates and FLSA class come from the assignment effective on that work date. Money and hours quantize to 2 decimal places, round half up.

Employees with `status` `terminated` as of period end are omitted from the register. `active`, `leave_of_absence`, `seasonal`, and `contractor` are included.

## Leave and exceptions

Leave accrual for the period is the sum over each work day of `leave_plans.accrual_hours_per_period / work_days` using the leave plan effective that day.

`leave_hours_taken` is the sum of `approved` leave request hours whose dates overlap the period. Pending and denied requests do not count.

Attendance exceptions listed on the register line are `missing_out` plus any `attendance_exceptions` rows for dates in the period. Late/early codes do not change hours by themselves.

## Outputs

`/app/hris/out/payroll-register.json`:

```json
{
  "period_id": "2026-W32",
  "cutoff": "2026-08-07T18:00:00Z",
  "closed_at": "2026-08-07T18:00:00Z",
  "employee_count": 1,
  "lines": [
    {
      "employee_id": "E000001",
      "cost_center": "CC-FIN-14",
      "flsa_status": "exempt",
      "regular_hours": 40.00,
      "overtime_hours": 0.00,
      "regular_pay": 1800.00,
      "overtime_pay": 0.00,
      "leave_hours_accrued": 3.82,
      "leave_hours_taken": 0.00,
      "gross_pay": 1800.00,
      "exceptions": []
    }
  ]
}
```

`lines` sorted by `employee_id`. `closed_at` equals the period `cutoff_at` (close is as-of cutoff, not a wall clock). Numeric fields are JSON numbers with 2 decimal places. `exceptions` is a list of `{date, code}` sorted by date then code.

`/app/hris/out/retro-journal.json`:

```json
{
  "period_id": "2026-W32",
  "entries": [
    {
      "employee_id": "E000001",
      "reason": "org_transfer",
      "effective_date": "2026-08-04",
      "from_cost_center": "CC-WH-02",
      "to_cost_center": "CC-FIN-14",
      "from_flsa": "non_exempt",
      "to_flsa": "exempt",
      "from_leave_plan": "PTO-NE",
      "to_leave_plan": "PTO-EX",
      "pre_hours": 10.00,
      "post_hours": 36.00,
      "pre_regular_pay": 200.00,
      "post_regular_pay": 1600.00,
      "overtime_hours": 0.00,
      "overtime_pay": 0.00,
      "leave_accrued": 3.82
    }
  ]
}
```

`entries` sorted by `employee_id` then `effective_date`. Include one `org_transfer` row for each in-period assignment change.

`/app/hris/out/hris-dump.json`:

```json
{
  "employee_count": 12000,
  "closed_periods": ["2026-W32"],
  "token_ok": true
}
```

`dump` does not require a successful close. `token_ok` is whether the token file currently validates.
