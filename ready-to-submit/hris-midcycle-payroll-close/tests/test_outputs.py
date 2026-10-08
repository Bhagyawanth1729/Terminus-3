"""Behavioral checks for the mid-cycle HRIS payroll close."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path("/app/hris")
BIN = ROOT / "bin" / "hrctl"
DB = ROOT / "var" / "hris.db"
OUT = ROOT / "out"
REGISTER = OUT / "payroll-register.json"
RETRO = OUT / "retro-journal.json"
DUMP = OUT / "hris-dump.json"
TOKEN = ROOT / "var" / "idp.token"


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(ROOT)
    if env:
        merged.update(env)
    return subprocess.run(
        [str(BIN), *args],
        cwd=str(ROOT),
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


def _register() -> dict:
    return json.loads(REGISTER.read_text(encoding="utf-8"))


def _retro() -> dict:
    return json.loads(RETRO.read_text(encoding="utf-8"))


def _line(emp_id: str) -> dict:
    matches = [row for row in _register()["lines"] if row["employee_id"] == emp_id]
    assert matches, emp_id
    return matches[0]


def test_f2p_register_schema_and_period():
    """Payroll register uses the contracted period, cutoff, and line fields."""
    data = _register()
    assert data["period_id"] == "2026-W32"
    assert data["cutoff"] == "2026-08-07T18:00:00Z"
    assert data["closed_at"] == "2026-08-07T18:00:00Z"
    assert data["employee_count"] == len(data["lines"])
    line = data["lines"][0]
    for key in (
        "employee_id",
        "cost_center",
        "flsa_status",
        "regular_hours",
        "overtime_hours",
        "regular_pay",
        "overtime_pay",
        "leave_hours_accrued",
        "leave_hours_taken",
        "gross_pay",
        "exceptions",
    ):
        assert key in line


def test_f2p_transfer_moves_cost_center():
    """An in-period transfer must land the register line on the new cost center."""
    assert _line("E000001")["cost_center"] == "CC-FIN-14"


def test_f2p_transfer_moves_flsa_class():
    """The same transfer must change the period-end FLSA class to exempt."""
    assert _line("E000001")["flsa_status"] == "exempt"


def test_f2p_transfer_zeroes_exempt_overtime():
    """After the FLSA change, leftover clock hours do not earn exempt OT premium."""
    row = _line("E000001")
    assert row["overtime_hours"] == 0
    assert row["overtime_pay"] == 0
    assert row["gross_pay"] == row["regular_pay"]


def test_f2p_transfer_leave_accrual_is_prorated():
    """Leave accrual mixes PTO-NE and PTO-EX across the effective date."""
    accrued = _line("E000001")["leave_hours_accrued"]
    assert accrued == 3.82


def test_f2p_retro_journal_records_org_transfer():
    """Retro journal contains the in-period org_transfer split for E000001."""
    entries = [row for row in _retro()["entries"] if row["employee_id"] == "E000001"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["reason"] == "org_transfer"
    assert entry["effective_date"] == "2026-08-04"
    assert entry["from_cost_center"] == "CC-WH-02"
    assert entry["to_cost_center"] == "CC-FIN-14"
    assert entry["from_flsa"] == "non_exempt"
    assert entry["to_flsa"] == "exempt"
    assert entry["pre_hours"] == 10.0
    assert entry["post_hours"] == 36.0
    assert entry["pre_regular_pay"] == 200.0
    assert entry["post_regular_pay"] == 1600.0


def test_f2p_exempt_employee_never_gets_ot_pay():
    """A full-week exempt employee records zero overtime hours and pay."""
    row = _line("E000002")
    assert row["flsa_status"] == "exempt"
    assert row["overtime_hours"] == 0
    assert row["overtime_pay"] == 0
    assert row["regular_pay"] == 1500.0


def test_f2p_non_exempt_overtime_uses_time_and_a_half():
    """A non-exempt employee over 40 hours receives 1.5x on the overtime portion."""
    row = _line("E000003")
    assert row["flsa_status"] == "non_exempt"
    assert row["overtime_hours"] > 0
    assert row["overtime_pay"] == round(row["overtime_hours"] * 18.0 * 1.5, 2)


def test_f2p_punches_after_cutoff_ignored():
    """Punches strictly after cutoff_at do not increase hours."""
    row = _line("E000004")
    assert row["regular_hours"] + row["overtime_hours"] == 40.0
    assert row["overtime_hours"] == 0


def test_f2p_approved_leave_hours_taken():
    """Approved leave overlapping the period appears on leave_hours_taken."""
    assert _line("E000005")["leave_hours_taken"] == 8.0


def test_f2p_missing_out_exception_listed():
    """An unpaired clock-in becomes a missing_out exception and drops those hours."""
    row = _line("E000006")
    codes = {(item["date"], item["code"]) for item in row["exceptions"]}
    assert ("2026-08-05", "missing_out") in codes
    assert row["regular_hours"] + row["overtime_hours"] == 32.0


def test_f2p_terminated_employees_omitted():
    """Terminated employees are not present on the register."""
    ids = {row["employee_id"] for row in _register()["lines"]}
    con = sqlite3.connect(str(DB))
    terminated = [
        r[0]
        for r in con.execute("SELECT employee_id FROM employees WHERE status = 'terminated'")
    ]
    con.close()
    assert terminated
    assert ids.isdisjoint(set(terminated))


def test_f2p_lines_sorted_by_employee_id():
    """Register lines are ordered by employee_id."""
    ids = [row["employee_id"] for row in _register()["lines"]]
    assert ids == sorted(ids)


def test_f2p_dump_reports_seed_scale_and_close():
    """Dump reports the 12000-employee seed and the closed period id."""
    data = json.loads(DUMP.read_text(encoding="utf-8"))
    assert data["employee_count"] == 12000
    assert data["closed_periods"] == ["2026-W32"]
    assert data["token_ok"] is True


def test_f2p_double_close_fails_and_keeps_bytes():
    """A second close-payroll exits 4 and does not rewrite register or retro bytes."""
    before_reg = REGISTER.read_bytes()
    before_retro = RETRO.read_bytes()
    cp = _run(["close-payroll", "--period", "2026-W32"])
    assert cp.returncode == 4
    assert REGISTER.read_bytes() == before_reg
    assert RETRO.read_bytes() == before_retro


def test_f2p_invalid_token_rejected():
    """A wrong local IdP token file fails closed with exit 3."""
    original = TOKEN.read_text(encoding="utf-8")
    try:
        TOKEN.write_text("not-a-valid-local-token\n", encoding="utf-8")
        cp = _run(["close-payroll", "--period", "2026-W32"])
        assert cp.returncode == 3
    finally:
        TOKEN.write_text(original, encoding="utf-8")


def test_f2p_hidden_transfer_changes_all_three_axes():
    """A verifier-only transfer on a cloned database moves cost center, FLSA, and leave together."""
    tmp = Path("/tmp/hris-hidden")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    shutil.copy2(DB, tmp / "hris.db")
    env = {
        "HRIS_DB": str(tmp / "hris.db"),
        "HRIS_OUT": str(tmp / "out"),
        "PYTHONPATH": str(ROOT),
    }
    (tmp / "out").mkdir()
    con = sqlite3.connect(str(tmp / "hris.db"))
    con.execute("DELETE FROM payroll_closes")
    con.commit()
    con.close()
    transfer = _run(
        [
            "transfer",
            "--employee",
            "E000003",
            "--effective",
            "2026-08-05",
            "--cost-center",
            "CC-FIN-99",
            "--flsa",
            "exempt",
            "--leave-plan",
            "PTO-EX",
        ],
        env=env,
    )
    assert transfer.returncode == 0, transfer.stderr
    close = _run(["close-payroll", "--period", "2026-W32"], env=env)
    assert close.returncode == 0, close.stderr
    data = json.loads((tmp / "out" / "payroll-register.json").read_text(encoding="utf-8"))
    row = next(item for item in data["lines"] if item["employee_id"] == "E000003")
    assert row["cost_center"] == "CC-FIN-99"
    assert row["flsa_status"] == "exempt"
    assert row["overtime_pay"] == 0
    retro = json.loads((tmp / "out" / "retro-journal.json").read_text(encoding="utf-8"))
    hit = [item for item in retro["entries"] if item["employee_id"] == "E000003"]
    assert hit and hit[0]["to_leave_plan"] == "PTO-EX"


def test_p2p_contract_and_idp_files_remain():
    """Public contract and local IdP metadata stay in place."""
    assert (ROOT / "docs" / "payroll-close-contract.md").is_file()
    assert (ROOT / "var" / "idp.json").is_file()
    assert TOKEN.is_file()


def test_p2p_period_cutoff_unchanged():
    """The seeded pay period cutoff is not rewritten to excuse after-cutoff punches."""
    con = sqlite3.connect(str(DB))
    row = con.execute(
        "SELECT cutoff_at, work_days FROM pay_periods WHERE period_id = '2026-W32'"
    ).fetchone()
    con.close()
    assert row[0] == "2026-08-07T18:00:00Z"
    assert row[1] == 5


def test_p2p_hrctl_binary_executable():
    """The public hrctl entrypoint remains executable."""
    assert BIN.is_file()
    assert os.access(BIN, os.X_OK)
    digest = hashlib.sha256(BIN.read_bytes()).hexdigest()
    assert len(digest) == 64
