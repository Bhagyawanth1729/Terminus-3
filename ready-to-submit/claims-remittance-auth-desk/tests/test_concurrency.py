"""Concurrent request, remittance, and audit ordering checks."""

from concurrent.futures import ThreadPoolExecutor

from conftest import connection, run_cli, scalar


def create_claim(index: int, billed: int = 100000) -> None:
    """Create a claim used by a later concurrent authorization."""
    result = run_cli(
        "OPEN", f"REQ-O{index:02d}", f"CL-O{index:02d}", "POL-STD", billed
    )
    assert result.returncode == 0


def test_simultaneous_identical_request_converges_on_one_result() -> None:
    """Two identical first uses must return one stored result, not an SQL error."""

    def submit() -> tuple[int, str, str]:
        result = run_cli("OPEN", "REQ-SAME", "CL-SAME", "POL-STD", "80000")
        return result.returncode, result.stdout, result.stderr

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: submit(), range(2)))
    assert outcomes[0][0] == outcomes[1][0] == 0
    assert outcomes[0][1] == outcomes[1][1]
    assert outcomes[0][2] == outcomes[1][2] == ""
    assert scalar("SELECT count(*) FROM request_record") == 1
    assert scalar("SELECT count(*) FROM audit_event") == 1


def test_competing_remittance_ids_have_one_committed_winner() -> None:
    """Concurrent claims using one remittance ID must leave exactly one row."""
    create_claim(1)
    create_claim(2)

    commands = [
        ("AUTHORIZE", "REQ-B01", "CL-O01", "1", "REM-BUSY", "10000"),
        ("AUTHORIZE", "REQ-B02", "CL-O02", "1", "REM-BUSY", "10000"),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda command: run_cli(*command), commands))
    assert sorted(result.returncode for result in results) == [0, 1]
    assert sum("code=REMITTANCE_EXISTS" in result.stdout for result in results) == 1
    assert scalar("SELECT count(*) FROM remittance") == 1


def test_unrelated_claim_authorizations_both_commit() -> None:
    """Locking one remittance must not reject an independent authorization."""
    create_claim(5)
    create_claim(6)
    commands = [
        ("AUTHORIZE", "REQ-U11", "CL-O05", "1", "REM-U11", "12000"),
        ("AUTHORIZE", "REQ-U12", "CL-O06", "1", "REM-U12", "12000"),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda command: run_cli(*command), commands))
    assert all(result.returncode == 0 for result in results)
    assert scalar("SELECT count(*) FROM remittance") == 2


def test_concurrent_accepts_publish_unique_gap_free_audit_numbers() -> None:
    """Concurrent unrelated opens must serialize only their committed audit IDs."""
    commands = [
        ("OPEN", f"REQ-Q{index:02d}", f"CL-Q{index:02d}", "POL-HD", "90000")
        for index in range(1, 5)
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda command: run_cli(*command), commands))
    assert all(result.returncode == 0 for result in results)
    with connection() as conn:
        sequences = [
            row[0]
            for row in conn.execute(
                "SELECT audit_sequence FROM audit_event ORDER BY audit_sequence"
            )
        ]
    assert sequences == list(range(1, 5))
    assert len({result.stdout for result in results}) == 4
