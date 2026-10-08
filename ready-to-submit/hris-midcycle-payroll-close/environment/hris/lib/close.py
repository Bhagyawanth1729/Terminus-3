from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from lib.dbutil import connect
from lib.paths import INCLUDED_STATUSES, OUT

TWOPLACES = Decimal("0.01")


def _q(value: Decimal | float | int) -> float:
    return float(Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP))


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _daterange(start: str, end: str) -> list[str]:
    cur = datetime.fromisoformat(start)
    last = datetime.fromisoformat(end)
    days = []
    while cur <= last:
        days.append(cur.date().isoformat())
        cur += timedelta(days=1)
    return days


def _workdays(start: str, end: str) -> list[str]:
    return [day for day in _daterange(start, end) if datetime.fromisoformat(day).weekday() < 5]


def _assignment_as_of(rows: list[sqlite3.Row], day: str) -> sqlite3.Row | None:
    chosen = None
    for row in rows:
        if row["effective_date"] <= day and (row["end_date"] is None or day < row["end_date"]):
            if chosen is None or row["effective_date"] > chosen["effective_date"]:
                chosen = row
    return chosen


def close_payroll(period_id: str) -> int:
    con = connect()
    try:
        period = con.execute(
            "SELECT * FROM pay_periods WHERE period_id = ?", (period_id,)
        ).fetchone()
        if period is None:
            return 5
        existing = con.execute(
            "SELECT register_digest FROM payroll_closes WHERE period_id = ?",
            (period_id,),
        ).fetchone()
        OUT.mkdir(parents=True, exist_ok=True)
        register_path = OUT / "payroll-register.json"
        retro_path = OUT / "retro-journal.json"

        # Starter: a second close appends another copy of the lines.
        employees = con.execute("SELECT * FROM employees").fetchall()
        assignments = con.execute("SELECT * FROM assignments ORDER BY employee_id, effective_date").fetchall()
        punches = con.execute("SELECT * FROM punches ORDER BY employee_id, punched_at").fetchall()
        leaves = con.execute("SELECT * FROM leave_requests").fetchall()
        exceptions = con.execute("SELECT * FROM attendance_exceptions").fetchall()
        plans = {row["plan_id"]: Decimal(str(row["accrual_hours_per_period"])) for row in con.execute("SELECT * FROM leave_plans")}

        asg_by_emp: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in assignments:
            asg_by_emp[row["employee_id"]].append(row)
        punches_by_emp: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in punches:
            punches_by_emp[row["employee_id"]].append(row)
        leave_by_emp: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in leaves:
            leave_by_emp[row["employee_id"]].append(row)
        exc_by_emp: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in exceptions:
            exc_by_emp[row["employee_id"]].append(row)

        start = period["start_date"]
        end = period["end_date"]
        work_days = _workdays(start, end)
        lines = []
        retro = []

        for emp in employees:
            emp_id = emp["employee_id"]
            asg_start = _assignment_as_of(asg_by_emp[emp_id], start)
            if asg_start is None:
                continue
            if emp["status"] == "terminated":
                continue

            # Starter: ignore cutoff and always use the period-start assignment.
            pairs = punches_by_emp[emp_id]
            hours_by_day: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
            missing = []
            i = 0
            while i < len(pairs):
                punch = pairs[i]
                if punch["direction"] != "in":
                    i += 1
                    continue
                out = None
                if i + 1 < len(pairs) and pairs[i + 1]["direction"] == "out":
                    out = pairs[i + 1]
                    i += 2
                else:
                    missing.append({"date": punch["punched_at"][:10], "code": "missing_out"})
                    i += 1
                    continue
                delta = _parse_ts(out["punched_at"]) - _parse_ts(punch["punched_at"])
                hours_by_day[punch["punched_at"][:10]] += Decimal(str(delta.total_seconds() / 3600.0))

            total = sum(hours_by_day.values(), Decimal("0"))
            regular_h = min(Decimal("40"), total)
            ot_h = max(Decimal("0"), total - Decimal("40"))
            hourly = Decimal(asg_start["hourly_rate_cents"] or 0) / Decimal("100")
            if asg_start["flsa_status"] == "exempt" and asg_start["salary_per_period_cents"]:
                hourly = Decimal(asg_start["salary_per_period_cents"]) / Decimal("100") / Decimal("40")
            regular_pay = regular_h * hourly
            ot_pay = ot_h * hourly * Decimal("1.5")
            plan = plans.get(asg_start["leave_plan"], Decimal("0"))
            accrued = plan
            taken = Decimal("0")
            for req in leave_by_emp[emp_id]:
                if req["status"] == "approved":
                    taken += Decimal(str(req["hours"]))
            excs = list(missing)
            for row in exc_by_emp[emp_id]:
                if start <= row["work_date"] <= end:
                    excs.append({"date": row["work_date"], "code": row["code"]})
            excs.sort(key=lambda item: (item["date"], item["code"]))
            lines.append(
                {
                    "employee_id": emp_id,
                    "cost_center": asg_start["cost_center"],
                    "flsa_status": asg_start["flsa_status"],
                    "regular_hours": _q(regular_h),
                    "overtime_hours": _q(ot_h),
                    "regular_pay": _q(regular_pay),
                    "overtime_pay": _q(ot_pay),
                    "leave_hours_accrued": _q(accrued),
                    "leave_hours_taken": _q(taken),
                    "gross_pay": _q(regular_pay + ot_pay),
                    "exceptions": excs,
                }
            )

        lines.sort(key=lambda row: row["employee_id"])
        if existing and register_path.is_file():
            prior = json.loads(register_path.read_text(encoding="utf-8"))
            prior_lines = prior.get("lines", [])
            lines = prior_lines + lines
        payload = {
            "period_id": period_id,
            "cutoff": period["cutoff_at"],
            "closed_at": period["cutoff_at"],
            "employee_count": len(lines),
            "lines": lines,
        }
        retro_payload = {"period_id": period_id, "entries": retro}
        register_text = json.dumps(payload, indent=2) + "\n"
        register_path.write_text(register_text, encoding="utf-8")
        retro_path.write_text(json.dumps(retro_payload, indent=2) + "\n", encoding="utf-8")
        digest = hashlib.sha256(register_text.encode("utf-8")).hexdigest()
        con.execute(
            "INSERT OR REPLACE INTO payroll_closes(period_id, closed_at, register_digest) VALUES (?, ?, ?)",
            (period_id, period["cutoff_at"], digest),
        )
        con.commit()
        return 0
    finally:
        con.close()
