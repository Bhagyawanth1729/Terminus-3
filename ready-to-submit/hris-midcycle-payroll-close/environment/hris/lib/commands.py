from __future__ import annotations

import json

from lib import auth, close as close_mod
from lib.dbutil import connect
from lib.paths import OUT


def cmd_transfer(args: dict) -> int:
    auth.require_token()
    con = connect()
    try:
        open_row = con.execute(
            """
            SELECT id FROM assignments
            WHERE employee_id = ? AND end_date IS NULL
            ORDER BY effective_date DESC LIMIT 1
            """,
            (args["employee"],),
        ).fetchone()
        if open_row:
            con.execute(
                "UPDATE assignments SET end_date = ? WHERE id = ?",
                (args["effective"], open_row["id"]),
            )
        rate = None
        salary = None
        prev = con.execute(
            """
            SELECT hourly_rate_cents, salary_per_period_cents, department_id
            FROM assignments WHERE employee_id = ? ORDER BY effective_date DESC LIMIT 1
            """,
            (args["employee"],),
        ).fetchone()
        if args["flsa"] == "non_exempt":
            rate = prev["hourly_rate_cents"] if prev else 2000
        else:
            salary = prev["salary_per_period_cents"] if prev and prev["salary_per_period_cents"] else 200000
        dept = prev["department_id"] if prev else "DEPT-GEN"
        con.execute(
            """
            INSERT INTO assignments(
              employee_id, effective_date, end_date, cost_center, department_id,
              flsa_status, leave_plan, hourly_rate_cents, salary_per_period_cents
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                args["employee"],
                args["effective"],
                args["cost_center"],
                dept,
                args["flsa"],
                args["leave_plan"],
                rate,
                salary,
            ),
        )
        con.commit()
    finally:
        con.close()
    return 0


def cmd_punch(args: dict) -> int:
    auth.require_token()
    con = connect()
    try:
        con.execute(
            "INSERT INTO punches(employee_id, punched_at, direction) VALUES (?, ?, ?)",
            (args["employee"], args["at"], args["direction"]),
        )
        con.commit()
    finally:
        con.close()
    return 0


def cmd_leave(args: dict) -> int:
    auth.require_token()
    con = connect()
    try:
        con.execute(
            """
            INSERT INTO leave_requests(employee_id, start_date, end_date, hours, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (args["employee"], args["start"], args["end"], float(args["hours"]), args["status"]),
        )
        con.commit()
    finally:
        con.close()
    return 0


def cmd_close(args: dict) -> int:
    auth.require_token()
    return close_mod.close_payroll(args["period"])


def cmd_dump(_args: dict) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        emp = con.execute("SELECT COUNT(*) AS c FROM employees").fetchone()["c"]
        periods = [
            row["period_id"]
            for row in con.execute("SELECT period_id FROM payroll_closes ORDER BY period_id")
        ]
    finally:
        con.close()
    payload = {
        "employee_count": int(emp),
        "closed_periods": periods,
        "token_ok": auth.token_ok(),
    }
    (OUT / "hris-dump.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0
