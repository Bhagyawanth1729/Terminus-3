"""Public command, state-machine, and build-boundary checks."""

import subprocess

from conftest import run_cli, scalar


def test_native_application_builds_and_reaches_the_database() -> None:
    """The submitted COBOL command must build and use the live schema."""
    dynamic = subprocess.run(
        ["readelf", "-d", "/app/claims/bin/claims-terminal"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "libcob.so" in dynamic
    assert "libocesql.so" in dynamic
    assert "libpq.so" in dynamic
    health = run_cli("HEALTH")
    assert health.returncode == 0
    assert health.stdout == "HEALTH|database=READY|schema=1\n"


def test_usage_errors_are_rejected_before_database_work() -> None:
    """Malformed commands must return exit 2 on stderr and write no rows."""
    missing = run_cli("AUTHORIZE", "REQ-U01", "CL-U01")
    signed = run_cli(
        "AUTHORIZE", "REQ-U02", "CL-U01", "1", "REM-U01", "+500"
    )
    assert missing.returncode == 2
    assert missing.stdout == ""
    assert "code=USAGE" in missing.stderr
    assert signed.returncode == 2
    assert scalar("SELECT count(*) FROM request_record") == 0


def test_open_authorize_close_follow_public_state_machine() -> None:
    """A normal claim must advance once per accepted lifecycle command."""
    opened = run_cli("OPEN", "REQ-L01", "CL-L01", "POL-STD", "100000")
    authorized = run_cli(
        "AUTHORIZE", "REQ-L02", "CL-L01", "1", "REM-L01", "50000"
    )
    closed = run_cli("CLOSE", "REQ-L03", "CL-L01", "2")
    status = run_cli("STATUS", "CL-L01")

    assert opened.stdout.endswith(
        "|revision=000001|state=OPEN|patient=000000000000|plan=000000000000|audit=0000000001\n"
    )
    assert "|revision=000002|state=ACTIVE|" in authorized.stdout
    assert "|revision=000003|state=CLOSED|" in closed.stdout
    assert "|state=CLOSED|" in status.stdout
    assert str(scalar("SELECT state FROM claim")).strip() == "CLOSED"


def test_clawback_requires_active_claim() -> None:
    """Clawback is refused on OPEN claims and accepted after authorization."""
    assert run_cli("OPEN", "REQ-C01", "CL-C01", "POL-ZERO", "20000").returncode == 0
    too_early = run_cli("CLAWBACK", "REQ-C02", "CL-C01", "1", "REM-X", "100")
    assert "code=INVALID_STATE" in too_early.stdout

    assert run_cli(
        "AUTHORIZE", "REQ-C03", "CL-C01", "1", "REM-C01", "20000"
    ).returncode == 0
    clawed = run_cli("CLAWBACK", "REQ-C04", "CL-C01", "2", "REM-C01", "5000")
    assert clawed.returncode == 0
    assert "|plan=000000015000|" in clawed.stdout
    assert scalar("SELECT clawed_cents FROM remittance") == 5000


def test_rejection_precedence_is_stable_and_recorded() -> None:
    """Unknown claim must win over later remittance and amount checks."""
    result = run_cli(
        "AUTHORIZE", "REQ-P01", "CL-NOPE", "999", "REM-Z9", "9"
    )
    assert result.returncode == 1
    assert result.stdout == (
        "ERR|request=REQ-P01|command=AUTHORIZE|code=UNKNOWN_CLAIM\n"
    )
    assert scalar("SELECT count(*) FROM request_record") == 1
    assert scalar("SELECT count(*) FROM audit_event") == 0


def test_unknown_policy_and_duplicate_claim_fail_closed() -> None:
    """OPEN must reject missing policies and duplicate claim identifiers."""
    missing = run_cli("OPEN", "REQ-R01", "CL-R01", "POL-MISSING", "1000")
    assert "code=UNKNOWN_POLICY" in missing.stdout
    assert run_cli("OPEN", "REQ-R02", "CL-R02", "POL-STD", "1000").returncode == 0
    duplicate = run_cli("OPEN", "REQ-R03", "CL-R02", "POL-STD", "2000")
    assert "code=CLAIM_EXISTS" in duplicate.stdout
    assert scalar("SELECT count(*) FROM claim") == 1
