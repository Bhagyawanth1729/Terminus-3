"""Idempotency, atomicity, remittance uniqueness, and audit checks."""

from __future__ import annotations

import os
import signal
import subprocess
import time

from conftest import CLI, cli_environment, connection, run_cli, scalar


def open_claim(request: str, claim: str, policy: str = "POL-STD", billed: int = 100000) -> str:
    """Create one claim and return its response."""
    result = run_cli("OPEN", request, claim, policy, billed)
    assert result.returncode == 0, result.stderr
    return result.stdout


def authorize(
    request: str,
    claim: str,
    revision: int,
    remittance: str,
    pay: int,
) -> subprocess.CompletedProcess[str]:
    """Authorize one remittance through the public command."""
    return run_cli("AUTHORIZE", request, claim, revision, remittance, pay)


def test_identical_retry_returns_byte_exact_result_once() -> None:
    """An exact retry must replay the stored line without another audit event."""
    first = open_claim("REQ-I01", "CL-I01")
    second = run_cli("OPEN", "REQ-I01", "CL-I01", "POL-STD", "100000")
    assert second.returncode == 0
    assert second.stdout == first
    assert scalar("SELECT count(*) FROM claim") == 1
    assert scalar("SELECT count(*) FROM audit_event") == 1


def test_request_id_reuse_with_one_changed_argument_conflicts() -> None:
    """A reused request ID must compare every parsed command argument."""
    open_claim("REQ-I02", "CL-I02")
    first = authorize("REQ-I03", "CL-I02", 1, "REM-I03", 20000)
    conflict = run_cli(
        "AUTHORIZE", "REQ-I03", "CL-I02", "1", "REM-I03", "20001"
    )
    assert first.returncode == 0
    assert conflict.returncode == 1
    assert conflict.stdout == (
        "ERR|request=REQ-I03|command=AUTHORIZE|code=REQUEST_CONFLICT\n"
    )
    assert scalar("SELECT charge_cents FROM remittance") == 20000
    assert scalar("SELECT count(*) FROM request_record") == 2


def test_business_rejection_is_permanent_and_replayable() -> None:
    """The first completed stale request must remain its permanent result."""
    open_claim("REQ-I04", "CL-I04")
    assert authorize("REQ-I05", "CL-I04", 1, "REM-I05", 10000).returncode == 0
    stale = run_cli("CLOSE", "REQ-I06", "CL-I04", "1")
    replay = run_cli("CLOSE", "REQ-I06", "CL-I04", "1")
    assert stale.returncode == 1
    assert replay.returncode == 0
    assert stale.stdout == replay.stdout
    assert "code=STALE_REVISION" in stale.stdout
    assert scalar("SELECT count(*) FROM audit_event") == 2


def test_duplicate_remittance_id_is_rejected() -> None:
    """An accepted remittance ID must remain unique across claims."""
    open_claim("REQ-D01", "CL-D01", billed=50000)
    open_claim("REQ-D02", "CL-D02", billed=50000)
    assert authorize("REQ-D03", "CL-D01", 1, "REM-SAME", 10000).returncode == 0
    duplicate = authorize("REQ-D04", "CL-D02", 1, "REM-SAME", 10000)
    assert duplicate.returncode == 1
    assert "code=REMITTANCE_EXISTS" in duplicate.stdout
    assert scalar("SELECT count(*) FROM remittance") == 1


def test_failed_clawback_preserves_plan_paid() -> None:
    """Clawback validation must finish before claim totals change."""
    open_claim("REQ-M01", "CL-M01", policy="POL-ZERO", billed=40000)
    assert authorize("REQ-M02", "CL-M01", 1, "REM-M01", 40000).returncode == 0
    before = scalar("SELECT plan_paid FROM claim")
    missing = run_cli("CLAWBACK", "REQ-M03", "CL-M01", "2", "REM-MISSING", "1000")
    assert missing.returncode == 1
    assert "code=UNKNOWN_REMITTANCE" in missing.stdout
    assert scalar("SELECT plan_paid FROM claim") == before

    over = run_cli("CLAWBACK", "REQ-M04", "CL-M01", "2", "REM-M01", "40001")
    assert over.returncode == 1
    assert "code=EXCEEDS_CLAWBACK" in over.stdout
    assert scalar("SELECT plan_paid FROM claim") == before
    assert scalar("SELECT clawed_cents FROM remittance") == 0


def test_rejections_and_replays_leave_a_gap_free_audit() -> None:
    """Only accepted mutations may consume the serialized audit counter."""
    first = open_claim("REQ-A11", "CL-A11")
    rejected = authorize("REQ-A12", "CL-A11", 1, "REM-Z9", 999999999)
    replay = run_cli("OPEN", "REQ-A11", "CL-A11", "POL-STD", "100000")
    closed = run_cli("CLOSE", "REQ-A13", "CL-A11", "1")
    assert first == replay.stdout
    assert rejected.returncode == 1
    assert closed.returncode == 0
    with connection() as conn:
        sequences = [
            row[0]
            for row in conn.execute(
                "SELECT audit_sequence FROM audit_event ORDER BY audit_sequence"
            )
        ]
    assert sequences == [1, 2]
    assert scalar("SELECT next_value FROM audit_counter") == 3


def test_process_termination_rolls_back_request_state_and_audit() -> None:
    """Killing the client during audit insertion must expose no partial claim."""
    with connection() as conn:
        conn.execute(
            "CREATE OR REPLACE FUNCTION verifier_pause_audit() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(20); RETURN NEW; END $$"
        )
        conn.execute(
            "CREATE TRIGGER verifier_pause BEFORE INSERT ON audit_event "
            "FOR EACH ROW EXECUTE FUNCTION verifier_pause_audit()"
        )

    process = subprocess.Popen(
        [str(CLI), "OPEN", "REQ-K01", "CL-K01", "POL-STD", "5000"],
        cwd="/app/claims",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=cli_environment(),
    )
    deadline = time.monotonic() + 10
    sleeping = False
    while time.monotonic() < deadline:
        with connection() as conn:
            sleeping = bool(
                conn.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE query LIKE 'INSERT INTO audit_event%')"
                ).fetchone()[0]
            )
        if sleeping:
            break
        time.sleep(0.1)
    assert sleeping
    os.kill(process.pid, signal.SIGKILL)
    process.wait(timeout=5)

    with connection() as conn:
        conn.execute("DROP TRIGGER verifier_pause ON audit_event")
        conn.execute("DROP FUNCTION verifier_pause_audit()")
    assert scalar("SELECT count(*) FROM claim") == 0
    assert scalar("SELECT count(*) FROM request_record") == 0
    assert scalar("SELECT count(*) FROM audit_event") == 0
    assert scalar("SELECT next_value FROM audit_counter") == 1
